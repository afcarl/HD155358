#This script:
#a) Draws masses from the MCMC posterior chain, runs migration simulations (K1, K2, mig_rate = free parameters). Run the C version of this code (faster, easier). 
#b) After migration ends, get some RV outputs and run an MCMC chain comparing it to the original data (x-stretch, x-translate, viewing angle = free parameters).
#c) See if you can find optimal parameters this way.

import multiprocessing as mp
import os
import sys
import random
import numpy as np
import pandas as pd
import emcee
import rebound
import glob
from progress.bar import Bar

#############General Functions######################
def retrieve_runs(dir):
    dir_prev = 'good_ones/'
    files = glob.glob(dir+'*.txt')
    runs = []
    for f in files:
        print f
        time, dE, N, migrate, damp1, damp2, migtime, DT, a1, e1, a2, e2, phi1, phi2, phi3, m1, m2, taua1, taue1, taua2, taue2 = np.loadtxt(open(f, 'r'), delimiter=',', unpack=True)
        seed = int(f.split('_sd')[1].split('.txt')[0])
        name = f.split(dir_prev)[1].split('.txt')[0]
        runs.append((m1[0],m2[0],1,migrate[0],damp1[0],damp2[0],seed,name))
    print runs
    return runs, len(runs)

def make_runs(N_runs):
    #draw masses from the posterior
    m1 = []
    m2 = []
    sini = []
    burnin = 1000
    ndim = 13
    #filename = '../emcee_chains/best_runs/hk_250walk_6000it/hk_250walk_6000it_chkpt5.npy'
    filename = '../emcee_chains/best_runs/hk_400walk_5000it_chkpt1.npy'
    samples = np.load(filename)[:, burnin:, :].reshape((-1, ndim))
    for theta in samples[np.random.randint(len(samples), size=N_runs)]:
        m1.append(theta[0])
        m2.append(theta[1])
        sini.append(theta[10])
    #make N_runs for simulation
    random.seed()
    runs = []
    mig_rate = random.sample(np.round(np.logspace(2.5,7,10*N_runs)), N_runs)
    K1 = random.sample(np.logspace(-1,3,10*N_runs), N_runs)
    K2 = random.sample(np.logspace(-1,3,10*N_runs), N_runs)
    path = 'output/'
    for i in xrange(0,N_runs):
        seed = int(10000*random.random())
        name = path+'taueinner_migrate%.1e_Kin%.1e_Kout%.1e_sd%d'%(mig_rate[i],K1[i],K2[i],seed)
        runs.append((m1[i],m2[i],sini[i],mig_rate[i],K1[i],K2[i],seed,name))
    return runs

def get_simRV(filename, time_sim, phi):
    AUyr2ms = 29682.77                   #AU/(yr/2pi) -> m/s
    sim = rebound.Simulation.from_file(filename+'.bin')
    tmax = sim.t
    rv = np.empty(0)
    for t in time_sim:
        sim.integrate(t+tmax,1)
        rv = np.append(rv,AUyr2ms*( sim.particles[0].vx*np.sin(phi) + sim.particles[0].vy*np.cos(phi) ))
    del sim
    return rv

#############emcee stuff############################
def lnlike(theta, filename, timeRV, dataRV, err2RV):
    x_s, x_t, y_s, y_t, phi, jitter2 = theta
    timesim = (timeRV + x_t)/x_s
    simRV = y_s*get_simRV(filename, timesim, phi) + y_t
    return -0.5*np.sum( (simRV - dataRV)**2/(err2RV + jitter2) + np.log(err2RV + jitter2) )

def lnprior(theta):
    x_s, x_t, y_s, y_t, phi, jitter2 = theta        #x-stretch, x-translate, y-stretch, phi (viewing angle), jitter2, RV offset
    if 0.5<x_s<2.5 and 0<x_t<600 and 0.25<y_s<4 and -40<y_t<40 and 0<=phi<2*np.pi and 0.<jitter2<60.:
        return 0
    return -np.inf

def lnprob(theta, filename, time_RV, data_RV, err2_RV):
    lnp = lnprior(theta)
    if not np.isfinite(lnp):
        return -np.inf
    lnL = lnlike(theta, filename, time_RV, data_RV, err2_RV)
    return lnp + lnL

def run_emcee(filename, time_RV, data_RV, err2_RV):
    theta_ini = [1.5,0,1,4,np.pi,10]  #x_stretch, x_translate, y_stretch, y_translate, phi, jitter2
    ndim, nwalkers, n_it, bar_checkpoints = len(theta_ini), 100, 2000, 100
    p0 = [theta_ini + 1e-4*np.random.randn(ndim) for i in range(nwalkers)]
    sampler = emcee.EnsembleSampler(nwalkers, ndim, lnprob, args=(filename, time_RV, data_RV, err2_RV));
    print("Running burn-in...")
    p0, lnp, rstate = sampler.run_mcmc(p0, 200)
    p = p0[np.argmax(lnp)]
    sampler.reset()
    # Re-sample the walkers near the best walker from the previous burn-in.
    pos = [p + 1e-8 * np.random.randn(ndim) for i in xrange(nwalkers)]
    bar = Bar("Running Production", max=bar_checkpoints)
    for i in range(bar_checkpoints):
        pos, _, _ = sampler.run_mcmc(pos, n_it/bar_checkpoints);
        bar.next()
    bar.finish()
    #save
    np.save(filename+'_chain.npy',sampler.chain)
    np.save(filename+'_lnprob.npy',sampler.lnprobability)
    np.save(filename+'_AF.npy',sampler.acceptance_fraction)
    #np.save(filename+'_ACT.npy',sampler.get_autocorr_time())   #leads to an error for some reason on prawn...

####################################################
#############Main Code##############################
#samples = np.load('../emcee_chains/best_runs/hk_250walk_6000it/hk_250walk_6000it_chkpt5.npy')[:,1000:,:].reshape((-1, 13))
#MAPP = np.percentile(samples, 50, axis=0)[:-2]

#each pool worker executes this
def execute(pars):
    os.system('./rebound %f %f %f %f %f %f %d %s'%pars)
    name = pars[-1].split('.txt')[0]
    try:
        print "\nPerforming MCMC fit."
        dtoyr2pi = 2*np.pi/365.              #days -> yr/2pi
        data = pd.read_csv('../RV.txt', delimiter=' ')
        time_RV, data_RV, err2_RV = (data['BJD']-data['BJD'][0])*dtoyr2pi, data['RV'], data['Unc']**2
        run_emcee(name, time_RV, data_RV, err2_RV)
    except:
        f = open('output/bad_sims.txt','a')
        f.write("Error simulating %s.txt. Skipped emcee.\n"%name)
        f.close()
        print "\nError simulating %s.txt. Skipping emcee.\n"%name

#Main multiprocess execution - Give sysname and letters of outer planets close to resonance
if __name__== '__main__':
    os.system('make')
    N_runs = 500
    runs = make_runs(N_runs)
    
    pool = mp.Pool(processes=np.min([N_runs, 5]))
    pool.map(execute, runs)
    pool.close()
    pool.join()

