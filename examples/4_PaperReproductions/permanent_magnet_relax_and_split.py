#!/usr/bin/env python
r"""
This example script allows the user to build
permanent magnet configurations for several stage-1 optimized
plasma boundaries, including the Landreman/Paul QA/QH designs,
the MUSE stellarator, the NCSX stellarator, and variations.

The script can be run in initialization, optimization, or post-processing mode: 
   srun -n 1 python permanent_magnet_relax_and_split.py muse_famus low initialization toroidal
   (i.e. configuration, resolution, run type, and coordinate system)
   srun -n 1 python permanent_magnet_relax_and_split.py muse_famus low optimization 0.0 1e-5 40 1e-20 0.40 0.0 1e6 20 toroidal
   (i.e. configuration, resolution, run type, l2_regularization, 
         error tolerance for the convex part of relax-and-split, # of iterations for the convex part,
         fB tolerance below which the algorithm will quit, l0-regularization,
         l1_regularization, nu, # of iterations for the overall relax-and-split, coordinate system 
   )
   srun -n 1 python permanent_magnet_relax_and_split.py muse_famus low post-processing 0.0 0.40 0.0 1e6 toroidal
   (i.e. configuration, resolution, run type, l2_regularization, 
         l0-regularization, l1_regularization, nu, coordinate system 
   )

Additional details regarding the command line parameters
and their defaults can be found in /src/simsopt/util/permanent_magnet_helper_functions.py.

"""

import os
import pickle
from matplotlib import pyplot as plt
from pathlib import Path
import numpy as np
from simsopt.geo import SurfaceRZFourier
from simsopt.objectives import SquaredFlux
from simsopt.field.magneticfieldclasses import DipoleField, ToroidalField
from simsopt.field.biotsavart import BiotSavart
from simsopt.geo import PermanentMagnetGrid
from simsopt.solve import relax_and_split 
from simsopt._core import Optimizable
from simsopt.util.permanent_magnet_helper_functions import *
import time

t_start = time.time()

# Read in all the required parameters
comm = None
config_flag, res_flag, run_type, reg_l2, epsilon, max_iter_MwPGP, min_fb, reg_l0, reg_l1, nu, max_iter_RS, dr, coff, poff, surface_flag, input_name, nphi, ntheta, famus_filename, coordinate_flag = read_input()

# Add cori scratch path
class_filename = "PM_optimizer_" + config_flag
scratch_path = '/global/cscratch1/sd/akaptano/'

# Read in the correct plasma equilibrium file
t1 = time.time()
TEST_DIR = (Path(__file__).parent / ".." / ".." / "tests" / "test_files").resolve()
surface_filename = TEST_DIR / input_name
if surface_flag == 'focus':
    s = SurfaceRZFourier.from_focus(surface_filename, range="half period", nphi=nphi, ntheta=ntheta)
elif surface_flag == 'wout':
    s = SurfaceRZFourier.from_wout(surface_filename, range="half period", nphi=nphi, ntheta=ntheta)
else:
    s = SurfaceRZFourier.from_vmec_input(surface_filename, range="half period", nphi=nphi, ntheta=ntheta)
t2 = time.time()
print("Done loading in plasma boundary surface, t = ", t2 - t1)

if run_type == 'initialization':
    # Make the output directory
    OUT_DIR = scratch_path + config_flag + "_" + coordinate_flag + "_nphi{0:d}_ntheta{1:d}_dr{2:.2e}_coff{3:.2e}_poff{4:.2e}/".format(nphi, ntheta, dr, coff, poff)
    print("Output directory = ", OUT_DIR)
    os.makedirs(OUT_DIR, exist_ok=True)

    # Don't have NCSX TF coils, just the Bn field on the surface
    # so have to treat the NCSX example separately.
    quadpoints_phi = np.linspace(0, 1, 2 * nphi, endpoint=True)
    qphi = len(quadpoints_phi)
    quadpoints_theta = np.linspace(0, 1, ntheta, endpoint=True)
    if config_flag != 'ncsx':
        t1 = time.time()

        # initialize the coils
        base_curves, curves, coils = initialize_coils(config_flag, TEST_DIR, OUT_DIR, s)

        # Set up BiotSavart fields
        bs = BiotSavart(coils)

        # Calculate average, approximate on-axis B field strength
        calculate_on_axis_B(bs, s)

        t2 = time.time()
        print("Done setting up biot savart, ", t2 - t1, " s")

        # Make higher resolution surface for plotting Bnormal
        if surface_flag == 'focus':
            s_plot = SurfaceRZFourier.from_focus(surface_filename, range="full torus", quadpoints_phi=quadpoints_phi, quadpoints_theta=quadpoints_theta)
        elif surface_flag == 'wout':
            s_plot = SurfaceRZFourier.from_wout(surface_filename, range="full torus", quadpoints_phi=quadpoints_phi, quadpoints_theta=quadpoints_theta)
        else:
            s_plot = SurfaceRZFourier.from_vmec_input(surface_filename, range="full torus", quadpoints_phi=quadpoints_phi, quadpoints_theta=quadpoints_theta)

        # Plot initial Bnormal on plasma surface from un-optimized BiotSavart coils
        make_Bnormal_plots(bs, s_plot, OUT_DIR, "biot_savart_initial")

        # If BiotSavart not yet optimized, optimize it
        if 'muse' not in config_flag:
            s, bs = coil_optimization(s, bs, base_curves, curves, OUT_DIR, s_plot, config_flag)

            # check after-optimization average on-axis magnetic field strength
            calculate_on_axis_B(bs, s)

        # Save optimized BiotSavart object
        bs.set_points(s.gamma().reshape((-1, 3)))
        Bnormal = np.sum(bs.B().reshape((nphi, ntheta, 3)) * s.unitnormal(), axis=2)
        biotsavart_json_str = bs.save(filename=OUT_DIR + 'BiotSavart.json')

        # Plot Bnormal on plasma surface from optimized BiotSavart coils
        bs.set_points(s_plot.gamma().reshape((-1, 3)))
        Bnormal_plot = np.sum(bs.B().reshape((qphi, ntheta, 3)) * s_plot.unitnormal(), axis=2)
        f_B_sf = SquaredFlux(s_plot, bs).J()
        print('BiotSavart f_B = ', f_B_sf)
        make_Bnormal_plots(bs, s_plot, OUT_DIR, "biot_savart_optimized")
    else:
        # Set up the contribution to Bnormal from a purely toroidal field.
        # Ampere's law for a purely toroidal field: 2 pi R B0 = mu0 I
        net_poloidal_current_Amperes = 3.7713e+6
        mu0 = 4 * np.pi * (1e-7)
        RB = mu0 * net_poloidal_current_Amperes / (2 * np.pi)
        print('B0 of toroidal field = ', RB)
        bs = ToroidalField(R0=1, B0=RB)

        # Check average on-axis magnetic field strength
        calculate_on_axis_B(bs, s)

        # Calculate Bnormal
        bs.set_points(s.gamma().reshape((-1, 3)))
        Bnormal = np.sum(bs.B().reshape((nphi, ntheta, 3)) * s.unitnormal(), axis=2)

        # Plot Bnormal on plasma surface from optimized BiotSavart coils
        s_plot = SurfaceRZFourier.from_wout(surface_filename, range="full torus", quadpoints_phi=quadpoints_phi, quadpoints_theta=quadpoints_theta)
        bs.set_points(s_plot.gamma().reshape((-1, 3)))
        Bnormal_plot = np.sum(bs.B().reshape((len(quadpoints_phi), len(quadpoints_theta), 3)) * s_plot.unitnormal(), axis=2)
        make_Bnormal_plots(bs, s_plot, OUT_DIR, "biot_savart_optimized")

    # Finally, initialize the permanent magnet class
    t1 = time.time()
    pm_opt = PermanentMagnetGrid(
        s, coil_offset=coff,
        dr=dr, plasma_offset=poff, Bn=Bnormal,
        filename=surface_filename, surface_flag=surface_flag, 
        coordinate_flag=coordinate_flag, famus_filename=famus_filename,
    )
    t2 = time.time()
    print('Done initializing the permanent magnet object')
    print('Process took t = ', t2 - t1, ' s')

    # If using a pre-made FAMUS grid of permanent magnet
    # locations, save the FAMUS grid and FAMUS solution.
    if famus_filename is not None:
        t1 = time.time()
        read_FAMUS_grid(famus_filename, pm_opt, s, s_plot, Bnormal, Bnormal_plot, OUT_DIR)
        t2 = time.time()
        print('Saving FAMUS solution took ', t2 - t1, ' s')

    t1 = time.time()
    # Save PM class object to file for optimization
    file_out = open(OUT_DIR + class_filename + ".pickle", "wb")

    # SurfaceRZFourier objects not pickle-able, so set to None
    # Presumably can fix this with Bharats new json functionality
    pm_opt.plasma_boundary = None
    pm_opt.rz_inner_surface = None
    pm_opt.rz_outer_surface = None
    pickle.dump(pm_opt, file_out)
    t2 = time.time()
    print('Pickling took ', t2 - t1, ' s')
    t_end = time.time()
    print('In total, script took ', t_end - t_start, ' s')

# Do optimization on pre-made grid of dipoles
elif run_type == 'optimization':
    IN_DIR = scratch_path + config_flag + "_" + coordinate_flag + "_nphi{0:d}_ntheta{1:d}_dr{2:.2e}_coff{3:.2e}_poff{4:.2e}/".format(nphi, ntheta, dr, coff, poff)

    # Make a subdirectory for the optimization output
    OUT_DIR = IN_DIR + "output_regl2{0:.2e}_regl0{1:.2e}_regl1{2:.2e}_nu{3:.2e}/".format(reg_l2, reg_l0, reg_l1, nu)
    os.makedirs(OUT_DIR, exist_ok=True)

    pickle_name = IN_DIR + class_filename + ".pickle"
    pm_opt = pickle.load(open(pickle_name, "rb", -1))
    print("Coordinate system being used = ", pm_opt.coordinate_flag)

    # Check that you loaded the correct file with the same parameters
    assert (dr == pm_opt.dr)
    assert (nphi == pm_opt.nphi)
    assert (ntheta == pm_opt.ntheta)
    assert (coff == pm_opt.coil_offset)
    assert (poff == pm_opt.plasma_offset)
    assert (surface_flag == pm_opt.surface_flag)
    assert (surface_filename == pm_opt.filename)

    # Read in the Bnormal or BiotSavart fields from any coils
    if config_flag != 'ncsx':
        bs = Optimizable.from_file(IN_DIR + 'BiotSavart.json')
        bs.set_points(s.gamma().reshape((-1, 3)))
        Bnormal = np.sum(bs.B().reshape((nphi, ntheta, 3)) * s.unitnormal(), axis=2)
    else:
        Bnormal = pm_opt.Bn

    # Set the pm_opt plasma boundary
    pm_opt.plasma_boundary = s
    print('Done initializing the permanent magnet object')

    # Set some hyperparameters for the optimization
    t1 = time.time()

    # Set an initial condition as all max
    m0 = np.ravel(np.array([pm_opt.m_maxima, pm_opt.m_maxima, pm_opt.m_maxima]).T) / np.sqrt(3)

    # Rescale the hyperparameters and then add contributions to ATA and ATb
    reg_l0, _, _, nu = rescale_for_opt(
        pm_opt, reg_l0, 0.0, 0.0, nu
    )

    # Set some hyperparameters for the optimization
    kwargs = initialize_default_kwargs()
    kwargs['nu'] = nu  # Strength of the "relaxation" part of relax-and-split
    kwargs['max_iter'] = max_iter_MwPGP  # Number of iterations to take in a convex step
    kwargs['max_iter_RS'] = max_iter_RS  # Number of total iterations of the relax-and-split algorithm
    kwargs['reg_l0'] = reg_l0

    # Optimize the permanent magnets, increasing L0 threshold as converging
    total_m_history = []
    total_mproxy_history = []
    total_RS_history = []
    num_i = 20
    skip = 10.0
    if not np.isclose(reg_l0, 0.0, atol=1e-16) or not np.isclose(reg_l1, 0.0, atol=1e-16):
        for i in range(num_i):
            kwargs['reg_l0'] = reg_l0 * (1 + i / skip)
            kwargs['reg_l1'] = reg_l1 * (1 + i / skip)
            print('Relax-and-split iteration ', i, ', L0 threshold = ', kwargs['reg_l0'])
            RS_history, m_history, m_proxy_history = relax_and_split(
                pm_opt,
                m0=m0,
                **kwargs
            )
            total_RS_history.append(RS_history)
            total_m_history.append(m_history)
            total_mproxy_history.append(m_proxy_history)
            m0 = pm_opt.m
    else:
        RS_history, m_history, m_proxy_history = relax_and_split( 
            pm_opt,
            m0=m0,
            **kwargs
        )
        total_RS_history.append(RS_history)
        total_m_history.append(m_history)
        total_mproxy_history.append(m_proxy_history)

    total_RS_history = np.ravel(np.array(total_RS_history))
    t2 = time.time()
    print('Done optimizing the permanent magnet object')
    print('Process took t = ', t2 - t1, ' s')
    make_optimization_plots(total_RS_history, total_m_history, total_mproxy_history, pm_opt, OUT_DIR)

    # Print effective permanent magnet volume
    M_max = 1.465 / (4 * np.pi * 1e-7)
    dipoles = pm_opt.m_proxy.reshape(pm_opt.ndipoles, 3)
    print('Volume of permanent magnets is = ', np.sum(np.sqrt(np.sum(dipoles ** 2, axis=-1))) / M_max)
    print('sum(|m_i|)', np.sum(np.sqrt(np.sum(dipoles ** 2, axis=-1))))

    # Save m and m_proxy solutions to txt files
    np.savetxt(OUT_DIR + class_filename + ".txt", pm_opt.m)
    np.savetxt(OUT_DIR + class_filename + "_proxy.txt", pm_opt.m_proxy)

    # write solution to FAMUS-type file
    write_pm_optimizer_to_famus(OUT_DIR, pm_opt)

    # Plot the sparse and less sparse solutions from SIMSOPT 
    t1 = time.time()
    m_copy = np.copy(pm_opt.m)
    pm_opt.m = pm_opt.m_proxy
    b_dipole_proxy = DipoleField(pm_opt)
    b_dipole_proxy.set_points(s.gamma().reshape((-1, 3)))
    b_dipole_proxy._toVTK(OUT_DIR + "Dipole_Fields_Sparse")
    pm_opt.m = m_copy
    b_dipole = DipoleField(pm_opt)
    b_dipole.set_points(s.gamma().reshape((-1, 3)))
    b_dipole._toVTK(OUT_DIR + "Dipole_Fields")
    t2 = time.time()
    print('Done setting up the Dipole Field class')
    print('Process took t = ', t2 - t1, ' s')

    # Print optimized metrics
    t1 = time.time()
    print("Total Bn without the PMs = ",
          np.sum((pm_opt.b_obj) ** 2) / 2.0)
    print("Total Bn without the coils = ",
          np.sum((pm_opt.A_obj @ pm_opt.m) ** 2) / 2.0)
    print("Total Bn = ",
          0.5 * np.sum((pm_opt.A_obj @ pm_opt.m - pm_opt.b_obj) ** 2))
    print("Total Bn (sparse) = ",
          0.5 * np.sum((pm_opt.A_obj @ pm_opt.m_proxy - pm_opt.b_obj) ** 2))

    # Compute metrics with permanent magnet results
    Nnorms = np.ravel(np.sqrt(np.sum(pm_opt.plasma_boundary.normal() ** 2, axis=-1)))
    Ngrid = pm_opt.nphi * pm_opt.ntheta
    ave_Bn_proxy = np.mean(np.abs(pm_opt.A_obj.dot(pm_opt.m_proxy) - pm_opt.b_obj) * np.sqrt(Ngrid / Nnorms)) / (2 * pm_opt.nphi * pm_opt.ntheta)
    Bn_Am = (pm_opt.A_obj.dot(pm_opt.m)) * np.sqrt(Ngrid / Nnorms)
    Bn_opt = (pm_opt.A_obj.dot(pm_opt.m) - pm_opt.b_obj) * np.sqrt(Ngrid / Nnorms)
    ave_Bn = np.mean(np.abs(Bn_opt) / (2 * pm_opt.nphi * pm_opt.ntheta))
    print('<B * n> with the optimized permanent magnets = {0:.8e}'.format(ave_Bn))
    print('<B * n> with the sparsified permanent magnets = {0:.8e}'.format(ave_Bn_proxy))

    Bnormal_dipoles = np.sum(b_dipole.B().reshape((nphi, ntheta, 3)) * s.unitnormal(), axis=-1)
    Bnormal_total = Bnormal + Bnormal_dipoles
    print("Average Bn with the PMs = ",
          np.mean(np.abs(Bnormal_total) / (2 * pm_opt.nphi * pm_opt.ntheta)))
    print('F_B INITIAL = ', SquaredFlux(s, b_dipole, -Bnormal).J())
    print('F_B INITIAL * 2 * nfp = ', 2 * s.nfp * SquaredFlux(pm_opt.plasma_boundary, b_dipole, -pm_opt.Bn).J())

    dipoles_m = pm_opt.m.reshape(pm_opt.ndipoles, 3)
    num_nonzero = np.count_nonzero(dipoles_m[:, 0] ** 2 + dipoles_m[:, 1] ** 2 + dipoles_m[:, 2] ** 2) / pm_opt.ndipoles * 100
    print("Number of possible dipoles = ", pm_opt.ndipoles)
    print("% of dipoles that are nonzero = ", num_nonzero)
    dipoles = np.ravel(dipoles)
    print('Dipole field setup done')

    make_optimization_plots(RS_history, m_history, m_proxy_history, pm_opt, OUT_DIR)
    t2 = time.time()
    print("Done printing and plotting, ", t2 - t1, " s")

    if comm is None or comm.rank == 0:
        # double the plasma surface resolution for the vtk plots
        t1 = time.time()
        qphi = 2 * s.nfp * nphi + 1
        qtheta = ntheta + 1
        endpoint = True
        quadpoints_phi = np.linspace(0, 1, qphi, endpoint=endpoint)
        quadpoints_theta = np.linspace(0, 1, qtheta, endpoint=endpoint)
        srange = 'full torus'

        if surface_flag == 'focus':
            s_plot = SurfaceRZFourier.from_focus(surface_filename, range=srange, quadpoints_phi=quadpoints_phi, quadpoints_theta=quadpoints_theta)
        elif surface_flag == 'wout':
            s_plot = SurfaceRZFourier.from_wout(surface_filename, range=srange, quadpoints_phi=quadpoints_phi, quadpoints_theta=quadpoints_theta)
        else:
            s_plot = SurfaceRZFourier.from_vmec_input(surface_filename, range=srange, quadpoints_phi=quadpoints_phi, quadpoints_theta=quadpoints_theta)

        if config_flag == 'ncsx':
            # Ampere's law for a purely toroidal field: 2 pi R B0 = mu0 I
            net_poloidal_current_Amperes = 3.7713e+6
            mu0 = 4 * np.pi * 1e-7
            RB = mu0 * net_poloidal_current_Amperes / (2 * np.pi)
            bs = ToroidalField(R0=1, B0=RB)
            bs.set_points(s_plot.gamma().reshape((-1, 3)))
            Bnormal = np.sum(bs.B().reshape((len(quadpoints_phi), len(quadpoints_theta), 3)) * s_plot.unitnormal(), axis=2)
        else:
            bs = Optimizable.from_file(IN_DIR + 'BiotSavart.json')
            bs.set_points(s_plot.gamma().reshape((-1, 3)))
            Bnormal = np.sum(bs.B().reshape((len(quadpoints_phi), len(quadpoints_theta), 3)) * s_plot.unitnormal(), axis=2)

        b_dipole.set_points(s_plot.gamma().reshape((-1, 3)))
        b_dipole_proxy.set_points(s_plot.gamma().reshape((-1, 3)))
        Bnormal_dipoles = np.sum(b_dipole.B().reshape((len(quadpoints_phi), len(quadpoints_theta), 3)) * s_plot.unitnormal(), axis=2)
        Bnormal_dipoles_proxy = np.sum(b_dipole_proxy.B().reshape((len(quadpoints_phi), len(quadpoints_theta), 3)) * s_plot.unitnormal(), axis=2)
        Bnormal_total = Bnormal + Bnormal_dipoles
        Bnormal_total_proxy = Bnormal + Bnormal_dipoles_proxy

        # For plotting Bn on the full torus surface at the end with just the dipole fields
        make_Bnormal_plots(bs, s_plot, OUT_DIR, "biot_savart_optimized")
        make_Bnormal_plots(b_dipole, s_plot, OUT_DIR, "only_m_optimized")
        make_Bnormal_plots(b_dipole_proxy, s_plot, OUT_DIR, "only_m_proxy_optimized")
        pointData = {"B_N": Bnormal_total[:, :, None]}
        s_plot.to_vtk(OUT_DIR + "m_optimized", extra_data=pointData)
        pointData = {"B_N": Bnormal_total_proxy[:, :, None]}
        s_plot.to_vtk(OUT_DIR + "m_proxy_optimized", extra_data=pointData)
        t2 = time.time()
        print('Done saving final vtk files, ', t2 - t1, " s")

        # Print optimized f_B and other metrics
        f_B_sf = SquaredFlux(s_plot, b_dipole, -Bnormal).J()
        print('f_B = ', f_B_sf)
        B_max = 1.465
        mu0 = 4 * np.pi * 1e-7
        total_volume = np.sum(np.sqrt(np.sum(pm_opt.m.reshape(pm_opt.ndipoles, 3) ** 2, axis=-1))) * s.nfp * 2 * mu0 / B_max
        total_volume_sparse = np.sum(np.sqrt(np.sum(pm_opt.m_proxy.reshape(pm_opt.ndipoles, 3) ** 2, axis=-1))) * s.nfp * 2 * mu0 / B_max
        print('Total volume for m and m_proxy = ', total_volume, total_volume_sparse)

        pm_opt.m = pm_opt.m_proxy
        b_dipole = DipoleField(pm_opt)
        b_dipole.set_points(s_plot.gamma().reshape((-1, 3)))
        f_B_sp = SquaredFlux(s_plot, b_dipole, -Bnormal).J()
        print('f_B_sparse = ', f_B_sp)
        dipoles = pm_opt.m_proxy.reshape(pm_opt.ndipoles, 3)
        num_nonzero_sparse = np.count_nonzero(dipoles[:, 0] ** 2 + dipoles[:, 1] ** 2 + dipoles[:, 2] ** 2) / pm_opt.ndipoles * 100
        np.savetxt(OUT_DIR + 'final_stats.txt', [f_B_sf, f_B_sp, num_nonzero, num_nonzero_sparse, total_volume, total_volume_sparse])

    # Save optimized permanent magnet class object
    file_out = open(OUT_DIR + class_filename + "_optimized.pickle", "wb")

    # SurfaceRZFourier objects not pickle-able, so set to None
    pm_opt.plasma_boundary = None
    pm_opt.rz_inner_surface = None
    pm_opt.rz_outer_surface = None
    pickle.dump(pm_opt, file_out)
elif run_type == 'post-processing':
    # Load in MPI, VMEC, etc. if doing a final run
    # to generate a VMEC wout file which can be
    # used to plot symmetry-breaking bmn, the flux
    # surfaces, epsilon_eff, etc.
    from mpi4py import MPI
    from simsopt.util.mpi import MpiPartition
    from simsopt.mhd.vmec import Vmec
    mpi = MpiPartition(ngroups=4)
    comm = MPI.COMM_WORLD

    # Load in optimized PMs
    IN_DIR = scratch_path + config_flag + "_" + coordinate_flag + "_nphi{0:d}_ntheta{1:d}_dr{2:.2e}_coff{3:.2e}_poff{4:.2e}/".format(nphi, ntheta, dr, coff, poff)

    # Read in the correct subdirectory with the optimization output
    OUT_DIR = IN_DIR + "output_regl2{0:.2e}_regl0{1:.2e}_regl1{2:.2e}_nu{3:.2e}/".format(reg_l2, reg_l0, reg_l1, nu)
    os.makedirs(OUT_DIR, exist_ok=True)
    pickle_name = IN_DIR + class_filename + ".pickle"
    pm_opt = pickle.load(open(pickle_name, "rb", -1))
    print('m = ', pm_opt.m)

    m_loadtxt = np.loadtxt(OUT_DIR + class_filename + ".txt")
    mproxy_loadtxt = np.loadtxt(OUT_DIR + class_filename + "_proxy.txt")

    # Optional code below for running the FAMUS solution through the post-processing routines
    # pms_name = 'zot80.focus'
    # m_loadtxt, _ = get_FAMUS_dipoles(pms_name)
    # mproxy_loadtxt = np.copy(m_loadtxt)
    pm_opt.m = m_loadtxt
    pm_opt.m_proxy = mproxy_loadtxt
    pm_opt.plasma_boundary = s

    b_dipole = DipoleField(pm_opt)
    b_dipole.set_points(s.gamma().reshape((-1, 3)))
    b_dipole._toVTK(OUT_DIR + "Dipole_Fields_fully_optimized")

    # run Poincare plots
    t1 = time.time()

    # Make higher resolution surface
    quadpoints_phi = np.linspace(0, 1, 2 * nphi, endpoint=True)
    qphi = len(quadpoints_phi)
    quadpoints_theta = np.linspace(0, 1, ntheta, endpoint=False)
    if surface_flag == 'focus':
        s_plot = SurfaceRZFourier.from_focus(surface_filename, range="full torus", quadpoints_phi=quadpoints_phi, quadpoints_theta=quadpoints_theta)
    elif surface_flag == 'wout':
        s_plot = SurfaceRZFourier.from_wout(surface_filename, range="full torus", quadpoints_phi=quadpoints_phi, quadpoints_theta=quadpoints_theta)
    else:
        s_plot = SurfaceRZFourier.from_vmec_input(surface_filename, range="full torus", quadpoints_phi=quadpoints_phi, quadpoints_theta=quadpoints_theta)

    # Read in the Bnormal or BiotSavart fields from any coils
    if config_flag != 'ncsx':
        pm_opt.m = pm_opt.m_proxy
        bs = Optimizable.from_file(IN_DIR + 'BiotSavart.json')
        bs.set_points(s_plot.gamma().reshape((-1, 3)))
        Bnormal = np.sum(bs.B().reshape((len(quadpoints_phi), len(quadpoints_theta), 3)) * s_plot.unitnormal(), axis=2)

        # need to call set_points again here for the combined field
        Bfield = Optimizable.from_file(IN_DIR + 'BiotSavart.json') + DipoleField(pm_opt)
        Bfield_tf = Optimizable.from_file(IN_DIR + 'BiotSavart.json') + DipoleField(pm_opt)
        Bfield.set_points(s.gamma().reshape((-1, 3)))

        # need to call set_points again here for the combined field
        m_copy = np.copy(pm_opt.m)
        pm_opt.m = pm_opt.m_proxy
        Bfield_mproxy = Optimizable.from_file(IN_DIR + 'BiotSavart.json') + DipoleField(pm_opt)
        Bfield_tf_mproxy = Optimizable.from_file(IN_DIR + 'BiotSavart.json') + DipoleField(pm_opt)
        Bfield_mproxy.set_points(s.gamma().reshape((-1, 3)))
        pm_opt.m = m_copy
    else:
        # Set up the contribution to Bnormal from a purely toroidal field.
        # Ampere's law for a purely toroidal field: 2 pi R B0 = mu0 I
        net_poloidal_current_Amperes = 3.7713e+6
        mu0 = 4 * np.pi * (1e-7)
        RB = mu0 * net_poloidal_current_Amperes / (2 * np.pi)
        bs = ToroidalField(R0=1, B0=RB)

        # Calculate Bnormal
        bs.set_points(s.gamma().reshape((-1, 3)))
        Bnormal = np.sum(bs.B().reshape((nphi, ntheta, 3)) * s.unitnormal(), axis=2)

        Bfield = ToroidalField(R0=1, B0=RB) + DipoleField(pm_opt)
        Bfield_tf = ToroidalField(R0=1, B0=RB) + DipoleField(pm_opt)
        Bfield.set_points(s.gamma().reshape((-1, 3)))

        m_copy = np.copy(pm_opt.m)
        pm_opt.m = pm_opt.m_proxy
        Bfield_mproxy = ToroidalField(R0=1, B0=RB) + DipoleField(pm_opt)
        Bfield_tf_mproxy = ToroidalField(R0=1, B0=RB) + DipoleField(pm_opt)
        Bfield_mproxy.set_points(s.gamma().reshape((-1, 3)))
        pm_opt.m = m_copy

    filename_poincare = 'm'
    run_Poincare_plots(s_plot, bs, b_dipole, config_flag, comm, filename_poincare, OUT_DIR)
    m_copy = np.copy(pm_opt.m)
    pm_opt.m = pm_opt.m_proxy
    b_dipole = DipoleField(pm_opt)
    b_dipole.set_points(s.gamma().reshape((-1, 3)))
    filename_poincare = 'mproxy'
    run_Poincare_plots(s_plot, bs, b_dipole, config_flag, comm, filename_poincare, OUT_DIR)
    pm_opt.m = m_copy
    t2 = time.time()
    print('Done with Poincare plots with the permanent magnets, t = ', t2 - t1)

    # Make the QFM surfaces
    t1 = time.time()
    qfm_surf = make_qfm(s_plot, Bfield)
    qfm_surf = qfm_surf.surface
    qfm_surf_mproxy = make_qfm(s, Bfield_mproxy)
    qfm_surf_mproxy = qfm_surf_mproxy.surface
    t2 = time.time()
    print("Making the two QFM surfaces took ", t2 - t1, " s")

    ### Always use the QA VMEC file and just change the boundary
    t1 = time.time()
    vmec_input = "../../tests/test_files/input.LandremanPaul2021_QA"
    equil = Vmec(vmec_input, mpi)
    equil.boundary = qfm_surf
    equil.run()

    ### Always use the QH VMEC file and just change the boundary
    vmec_input = "../../tests/test_files/input.LandremanPaul2021_QH_reactorScale_lowres"
    equil = Vmec(vmec_input, mpi)
    equil.boundary = qfm_surf_mproxy
    equil.run()

    t2 = time.time()
    print("VMEC took ", t2 - t1, " s")

t_end = time.time()
print('Total time = ', t_end - t_start)

# Show the figures
# plt.show()