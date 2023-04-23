'''
    This example sript uses the GPMO backtracking algorithm with 
    arbitrarily-defined polarization vectors to optimize magnets in an 
    arrangement around the NCSX plasma in the C09R00 configuration with 
    an average magnetic field strength on axis of about 0.5 T.
    This test applies the backtracking approach to the PM4Stell magnet arrangement
    with face-triplet polarizations. The threshold angle for removal of magnet 
    pairs is set by the user, unlike the normal backtracking algorithm
    which defaults to threshold_angle = 180 degrees (only remove adjacent 
    dipoles if they are exactly equal and opposite).

    PM4Stell functionality and related code obtained courtesy of
    Ken Hammond and the PM4Stell + MAGPIE teams. 
'''

import os
import numpy as np
from matplotlib import pyplot as plt
import time
from simsopt.geo import SurfaceRZFourier, PermanentMagnetGrid
from simsopt.field import BiotSavart, DipoleField
from simsopt.field import Coil
from simsopt.solve import GPMO
from simsopt.util.permanent_magnet_helper_functions \
    import initialize_default_kwargs, write_pm_optimizer_to_famus, make_Bnormal_plots
from simsopt.util import FocusPlasmaBnormal, FocusData, read_focus_coils
from simsopt.util.polarization_project import polarization_axes, orientation_phi, \
    discretize_polarizations
t_start = time.time()

# Set some parameters
N = 16
nphi = N
ntheta = N
nfp = 3
algorithm = 'baseline'  # 'ArbVec_backtracking'
nBacktracking = 500 
nAdjacent = 10
nIter_max = 40000
max_nMagnets = 10000
thresh_angle = np.pi / np.sqrt(2)
nHistory = 100
out_dir = 'PM4Stell_' + str(int(thresh_angle * 180 / np.pi)) + 'deg_nb' + str(nBacktracking) + '_na' + str(nAdjacent) + '/' 
os.makedirs(out_dir, exist_ok=True)
print('out directory = ', out_dir)

# Obtain the plasma boundary for the NCSX configuration
dir_pm4stell = '../../tests/test_files/'
dir_ncsx_surf = dir_pm4stell + ''
fname_plasma = dir_ncsx_surf + 'c09r00_B_axis_half_tesla_PM4Stell.plasma'
lcfs_ncsx = SurfaceRZFourier.from_focus(fname_plasma, range='half period', \
                                        nphi=nphi, ntheta=ntheta)
s1 = SurfaceRZFourier.from_focus(fname_plasma, range='half period', \
                                 nphi=nphi, ntheta=ntheta)
s2 = SurfaceRZFourier.from_focus(fname_plasma, range='half period', \
                                 nphi=nphi, ntheta=ntheta)

# Make higher resolution surface for plotting Bnormal
qphi = 2 * nphi
quadpoints_phi = np.linspace(0, 1, qphi, endpoint=True)
quadpoints_theta = np.linspace(0, 1, ntheta, endpoint=True)
s_plot = SurfaceRZFourier.from_focus(
    fname_plasma, range="full torus",
    quadpoints_phi=quadpoints_phi, quadpoints_theta=quadpoints_theta
)

# Obtain the normal field on the plasma boundary arising from plasma currents
bnormal_obj_ncsx = FocusPlasmaBnormal(fname_plasma)
bn_plasma = bnormal_obj_ncsx.bnormal_grid(nphi, ntheta, 'half period')

# Obtain the NCSX TF coil data and calculate their normal field on the boundary
dir_ncsx_coils = dir_pm4stell + ''
fname_ncsx_coils = dir_ncsx_coils + 'tf_only_half_tesla_symmetry_baxis_PM4Stell.focus'
# ncsx_tfcoils = read_focus_coils(fname_ncsx_coils, nfp)
base_curves, base_currents, ncoils = read_focus_coils(fname_ncsx_coils)
coils = []
for i in range(ncoils):
    coils.append(Coil(base_curves[i], base_currents[i]))
base_currents[0].fix_all()

# fix all the coil shapes
for i in range(ncoils):
    base_curves[i].fix_all()

# Obtain Bnormal from the plasma and the coils
ncsx_tfcoils = coils
bs_tfcoils = BiotSavart(ncsx_tfcoils)
bs_tfcoils.set_points(lcfs_ncsx.gamma().reshape((-1, 3)))
bn_tfcoils = np.sum(bs_tfcoils.B().reshape((nphi, ntheta, 3)) \
                    * lcfs_ncsx.unitnormal(), axis=2)
bn_total = bn_plasma + bn_tfcoils
make_Bnormal_plots(bs_tfcoils, s_plot, out_dir, "biot_savart_initial")

# Obtain data on the magnet arrangement
fname_argmt = dir_pm4stell + 'magpie_trial104b_PM4Stell.focus'
fname_corn = dir_pm4stell + 'magpie_trial104b_corners_PM4Stell.csv'
mag_data = FocusData(fname_argmt)
nMagnets_tot = mag_data.nMagnets

# Determine the allowable polarization types and reject the negatives
pol_axes = np.zeros((0, 3))
pol_type = np.zeros(0, dtype=int)
pol_axes_f, pol_type_f = polarization_axes(['face'])
ntype_f = int(len(pol_type_f)/2)
pol_axes_f = pol_axes_f[:ntype_f, :]
pol_type_f = pol_type_f[:ntype_f]
pol_axes = np.concatenate((pol_axes, pol_axes_f), axis=0)
pol_type = np.concatenate((pol_type, pol_type_f))
pol_axes_fe_ftri, pol_type_fe_ftri = polarization_axes(['fe_ftri'])
ntype_fe_ftri = int(len(pol_type_fe_ftri)/2)
pol_axes_fe_ftri = pol_axes_fe_ftri[:ntype_fe_ftri, :]
pol_type_fe_ftri = pol_type_fe_ftri[:ntype_fe_ftri] + 1
pol_axes = np.concatenate((pol_axes, pol_axes_fe_ftri), axis=0)
pol_type = np.concatenate((pol_type, pol_type_fe_ftri))
pol_axes_fc_ftri, pol_type_fc_ftri = polarization_axes(['fc_ftri'])
ntype_fc_ftri = int(len(pol_type_fc_ftri)/2)
pol_axes_fc_ftri = pol_axes_fc_ftri[:ntype_fc_ftri, :]
pol_type_fc_ftri = pol_type_fc_ftri[:ntype_fc_ftri] + 2
pol_axes = np.concatenate((pol_axes, pol_axes_fc_ftri), axis=0)
pol_type = np.concatenate((pol_type, pol_type_fc_ftri))

# Read in the phi coordinates and set the pol_vectors
ophi = orientation_phi(fname_corn)[:nMagnets_tot]
discretize_polarizations(mag_data, ophi, pol_axes, pol_type)
pol_vectors = np.zeros((nMagnets_tot, len(pol_type), 3))
pol_vectors[:, :, 0] = mag_data.pol_x
pol_vectors[:, :, 1] = mag_data.pol_y
pol_vectors[:, :, 2] = mag_data.pol_z

# Initialize the permanent magnet grid from the PM4Stell arrangement
pm_ncsx = PermanentMagnetGrid(lcfs_ncsx, s1, s2,
                              Bn=bn_total, 
                              coordinate_flag='cartesian', 
                              pol_vectors=pol_vectors)
pm_ncsx.geo_setup_from_famus(fname_argmt)

# Optimize with the GPMO algorithm
kwargs = initialize_default_kwargs('GPMO')
kwargs['K'] = nIter_max
kwargs['nhistory'] = nHistory
if algorithm == 'backtracking' or algorithm == 'ArbVec_backtracking':
    kwargs['backtracking'] = nBacktracking
    kwargs['Nadjacent'] = nAdjacent
    kwargs['dipole_grid_xyz'] = np.ascontiguousarray(pm_ncsx.dipole_grid_xyz)
    if algorithm == 'ArbVec_backtracking':
        kwargs['thresh_angle'] = thresh_angle
        kwargs['max_nMagnets'] = max_nMagnets
t1 = time.time()
R2_history, Bn_history, m_history = GPMO(pm_ncsx, algorithm, **kwargs)
dt = time.time() - t1
print('GPMO took t = ', dt, ' s')

# Make BiotSavart object from the dipoles and plot solution 
b_dipole = DipoleField(
    pm_ncsx.dipole_grid_xyz,
    pm_ncsx.m,
    nfp=s_plot.nfp,
    coordinate_flag=pm_ncsx.coordinate_flag,
    m_maxima=pm_ncsx.m_maxima,
)
b_dipole.set_points(s_plot.gamma().reshape((-1, 3)))
b_dipole._toVTK(out_dir + "Dipole_Fields")
make_Bnormal_plots(bs_tfcoils + b_dipole, s_plot, out_dir, "biot_savart_optimized")
Bnormal_coils = np.sum(bs_tfcoils.B().reshape((qphi, ntheta, 3)) * s_plot.unitnormal(), axis=-1)
Bnormal_dipoles = np.sum(b_dipole.B().reshape((qphi, ntheta, 3)) * s_plot.unitnormal(), axis=-1)
Bnormal_plasma = bnormal_obj_ncsx.bnormal_grid(qphi, ntheta, 'full torus')
Bnormal_total = Bnormal_plasma + Bnormal_coils + Bnormal_dipoles 
pointData = {"B_N": Bnormal_plasma[:, :, None]}
s_plot.to_vtk(out_dir + "Bnormal_plasma", extra_data=pointData)
pointData = {"B_N": Bnormal_dipoles[:, :, None]}
s_plot.to_vtk(out_dir + "Bnormal_dipoles", extra_data=pointData)
pointData = {"B_N": Bnormal_coils[:, :, None]}
s_plot.to_vtk(out_dir + "Bnormal_coils", extra_data=pointData)
pointData = {"B_N": Bnormal_total[:, :, None]}
s_plot.to_vtk(out_dir + "Bnormal_total", extra_data=pointData)

# Save files
if False:
    write_pm_optimizer_to_famus(out_dir, pm_ncsx)
    np.savetxt(out_dir + 'R2_history.txt', R2_history)
    np.savetxt(out_dir + 'absBn_history.txt', Bn_history)
    nmags = m_history.shape[0]
    nhist = m_history.shape[2]
    m_history_2d = m_history.reshape((nmags*m_history.shape[1], nhist))
    np.savetxt(out_dir + 'm_history_nmags=%d_nhist=%d.txt' % (nmags, nhist), \
               m_history_2d)
t_end = time.time()  
print('Script took in total t = ', t_end - t_start, ' s')

# Plot optimization results as function of iterations
plt.figure()
plt.semilogy(R2_history, label=r'$f_B$')
plt.semilogy(Bn_history, label=r'$<|Bn|>$')
plt.grid(True)
plt.xlabel('K')
plt.ylabel('Metric values')
plt.legend()
plt.show()