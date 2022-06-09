import numpy as np
import sys
from pyevtk.hl import pointsToVTK
from scipy.optimize import minimize
from scipy.io import netcdf
from simsopt.field.coil import Current
from simsopt.geo.curvexyzfourier import CurveXYZFourier
from simsopt.geo.surfacerzfourier import SurfaceRZFourier
from simsopt.field.magneticfieldclasses import DipoleField
from simsopt.objectives.fluxobjective import SquaredFlux
from simsopt.geo.curveobjectives import CurveLength, CurveCurveDistance, \
    MeanSquaredCurvature, LpCurveCurvature, CurveSurfaceDistance
from simsopt.objectives.utilities import QuadraticPenalty
from simsopt.geo.curve import curves_to_vtk
import time


def sanitised_input(prompt, type_=None, min_=None, max_=None, range_=None, default_=None):
    """ 
        Copied function from https://stackoverflow.com/questions/23294658/asking-the-user-for-input-until-they-give-a-valid-response for asking user for 
        repeated input values. 
    """
    if min_ is not None and max_ is not None and max_ < min_:
        raise ValueError("min_ must be less than or equal to max_.")
    while True:
        ui = input(prompt + '(Press enter for default value = ' + str(default_) + ') ')
        if ui == '':
            return default_
        elif type_ is not None:
            try:
                ui = type_(ui)
            except ValueError:
                print("Input type must be {0}.".format(type_.__name__))
                continue
        if max_ is not None and ui > max_:
            print("Input must be less than or equal to {0}.".format(max_))
        elif min_ is not None and ui < min_:
            print("Input must be greater than or equal to {0}.".format(min_))
        elif range_ is not None and ui not in range_:
            if isinstance(range_, range):
                template = "Input must be between {0.start} and {0.stop}."
                print(template.format(range_))
            else:
                template = "Input must be {0}."
                if len(range_) == 1:
                    print(template.format(*range_))
                else:
                    expected = " or ".join((
                        ", ".join(str(x) for x in range_[:-1]),
                        str(range_[-1])
                    ))
                    print(template.format(expected))
        else:
            return ui


def read_input():
    """
        Wrapper function for santitised_input function that reads in 
        all the parameters needed for the permanent magnet optimization.
        Provides interactive user inputs if running the code from an
        interactive compute node, otherwise needs command line arguments
        to work correctly from a slurm script.
    """
    if len(sys.argv) < 2:
        raise ValueError(
            'You must specify if the run is interactive or not '
            'with a command line flag of True or False.'
        )
    else:
        interactive = str(sys.argv[1])
        if interactive not in ['True', 'False']:
            raise ValueError(
                'Flag for interactivity must be True or False'
            )
        interactive = (interactive == 'True')

    if interactive:
        config_flag = sanitised_input("Enter the plasma configuration name: ", str, range_=('qa', 'qa_nonplanar', 'QH', 'qh', 'qh_nonplanar', 'muse', 'muse_famus', 'ncsx'), default_='muse_famus')
        res_flag = sanitised_input("Enter the resolution: ", str, range_=('low', 'medium', 'high'), default_='low')
        final_run = sanitised_input("Final polished run with VMEC + poincare plots? ", str, range_=('False', 'True'), default_='False')
        final_run = (final_run == 'True')
        reg_l2 = sanitised_input("L2 Regularization = ", float, 0.0, 1.0, default_=0.0)
        epsilon = sanitised_input("Error tolerance for the convex subproblem = ", float, 0.0, 1.0, default_=1e-2)
        max_iter_MwPGP = sanitised_input("Maximum iterations for the convex subproblem = ", int, 0, 1e5, default_=100)
        min_fb = sanitised_input("Value of f_B metric to end the algorithm on = ", float, 0.0, 1.0, default_=1e-20)
        reg_l0 = sanitised_input("L0 Regularization = ", float, 0.0, 1.0, default_=0.0)
        if np.isclose(reg_l0, 0.0):
            nu = 1.0e100
            max_iter_RS = 1
        else:
            nu = sanitised_input("nu (relax-and-split hyperparameter) = ", float, 0.0, 1e100, default_=1e6)
            max_iter_RS = sanitised_input("Maximum number of relax-and-split iterations: ", int, 0, 1e5, default_=10) 

    else: 
        if len(sys.argv) < 5:
            print(
                "Error! If the run is interactive, then "
                "you must specify at least 4 arguments: "
                "the flag to indicate if the run is interactive, "
                "the configuration flag, resolution flag, final run flag "
                "(whether to run time-intensive processes like QFMs, Poincare "
                "plots, VMEC, etc.), and (optionally) the L0 and L2 regularizer"
                " strengths."
            )
            exit(1)
        config_flag = str(sys.argv[2])
        if config_flag not in ['qa', 'qa_nonplanar', 'QH', 'qh', 'qh_nonplanar', 'muse', 'muse_famus', 'ncsx']:
            raise ValueError(
                "Error! The configuration flag must specify one of "
                "the pre-set plasma equilibria: qa, qa_nonplanar, "
                "QH, qh, qh_nonplanar, muse, muse_famus, or ncsx. "
            )
        res_flag = str(sys.argv[3])
        if res_flag not in ['low', 'medium', 'high']:
            raise ValueError(
                "Error! The resolution flag must specify one of "
                "low or high."
            )
        final_run = str(sys.argv[4])
        if final_run not in ['True', 'False']:
            raise ValueError(
                "Error! The final_run flag must specify one of "
                "True or False."
            )
        final_run = (final_run == 'True')

        # L2 regularization
        if len(sys.argv) >= 6:
            reg_l2 = float(sys.argv[5])
        else:
            reg_l2 = 1e-12

        # Error tolerance for declaring convex problem finished
        if len(sys.argv) >= 7:
            epsilon = float(sys.argv[6])
        else:
            epsilon = 1e-2

        # Maximum iterations for solving the convex problem
        if len(sys.argv) >= 8:
            max_iter_MwPGP = int(sys.argv[7])
        else:
            max_iter_MwPGP = 100

        # Error tolerance for declaring nonconvex problem finished
        if len(sys.argv) >= 9:
            min_fb = float(sys.argv[8])
        else:
            min_fb = 1e-20

        # L0 regularization
        if len(sys.argv) >= 10:
            reg_l0 = float(sys.argv[9])
        else:
            reg_l0 = 0.0  # default is no L0 norm

        # nu (relax-and-split hyperparameter)
        if len(sys.argv) >= 11:
            nu = float(sys.argv[10])

        # Set to huge value if reg_l0 is zero so it is ignored
        if np.isclose(reg_l0, 0.0, atol=1e-16):
            nu = 1e100

        # Maximum iterations for solving the nonconvex problem
        if len(sys.argv) >= 12:
            max_iter_RS = int(sys.argv[11])
        else:
            max_iter_RS = 100

    # Set the remaining parameters
    surface_flag = 'vmec'
    pms_name = None
    is_premade_famus_grid = False
    if res_flag == 'high':
        nphi = 64
        ntheta = 64
    elif res_flag == 'medium':
        nphi = 16
        ntheta = 16
    else:
        nphi = 8
        ntheta = 8
    if config_flag == 'muse':
        dr = 0.01
        coff = 0.1
        poff = 0.05
        surface_flag = 'focus'
        input_name = 'input.' + config_flag 
    if config_flag == 'muse_famus':
        dr = 0.01
        coff = 0.1
        poff = 0.02
        surface_flag = 'focus'
        input_name = 'input.muse'
        pms_name = 'zot80.focus'
        is_premade_famus_grid = True
    elif 'QH' in config_flag:
        dr = 0.4
        coff = 2.4
        poff = 1.6
        input_name = 'wout_LandremanPaul2021_' + config_flag[:2].upper() + '_reactorScale_lowres_reference.nc'
        surface_flag = 'wout'
    elif 'qa' in config_flag or 'qh' in config_flag:
        dr = 0.01
        coff = 0.06
        poff = 0.04
        if 'qa' in config_flag:
            input_name = 'input.LandremanPaul2021_' + config_flag[:2].upper()
        else:
            input_name = 'wout_LandremanPaul_' + config_flag[:2].upper() + '_variant.nc'
            surface_flag = 'wout'
    elif config_flag == 'ncsx':
        dr = 0.02
        coff = 0.02
        poff = 0.1
        surface_flag = 'wout'
        input_name = 'wout_c09r00_fixedBoundary_0.5T_vacuum_ns201.nc'
        pms_name = 'init_orient_pm_nonorm_5E4_q4_dp.focus' 
        is_premade_famus_grid = True

    print('Config flag = ', config_flag)
    print('Resolution flag = ', res_flag)
    print('Final run = ', final_run)
    print('L2 regularization = ', reg_l2)
    print('Error tolerance for the convex subproblem = ', epsilon)
    print('Maximum iterations for the convex subproblem = ', max_iter_MwPGP)
    print('min f_B value (if achieved, algorithm quits) = ', min_fb)
    print('L0 regularization = ', reg_l0)
    print('nu = ', nu)
    print('Maximum iterations for relax-and-split = ', max_iter_RS)
    print('Input file name = ', input_name)
    print('nphi = ', nphi)
    print('ntheta = ', ntheta)
    print('Pre-made grid of dipoles (if the grid is from a FAMUS run) = ', pms_name)
    return config_flag, res_flag, final_run, reg_l2, epsilon, max_iter_MwPGP, min_fb, reg_l0, nu, max_iter_RS, dr, coff, poff, surface_flag, input_name, nphi, ntheta, pms_name, is_premade_famus_grid


def read_focus_coils(filename):
    """
        Reads in the coils for the MUSE phased TF coils.
    """
    ncoils = np.loadtxt(filename, skiprows=1, max_rows=1, dtype=int)
    order = np.loadtxt(filename, skiprows=8, max_rows=1, dtype=int)
    coilcurrents = np.zeros(ncoils)
    xc = np.zeros((ncoils, order + 1))
    xs = np.zeros((ncoils, order + 1))
    yc = np.zeros((ncoils, order + 1))
    ys = np.zeros((ncoils, order + 1))
    zc = np.zeros((ncoils, order + 1))
    zs = np.zeros((ncoils, order + 1))
    for i in range(ncoils):
        coilcurrents[i] = np.loadtxt(filename, skiprows=6 + 14 * i, max_rows=1, usecols=1)
        xc[i, :] = np.loadtxt(filename, skiprows=10 + 14 * i, max_rows=1, usecols=range(order + 1))
        xs[i, :] = np.loadtxt(filename, skiprows=11 + 14 * i, max_rows=1, usecols=range(order + 1))
        yc[i, :] = np.loadtxt(filename, skiprows=12 + 14 * i, max_rows=1, usecols=range(order + 1))
        ys[i, :] = np.loadtxt(filename, skiprows=13 + 14 * i, max_rows=1, usecols=range(order + 1))
        zc[i, :] = np.loadtxt(filename, skiprows=14 + 14 * i, max_rows=1, usecols=range(order + 1))
        zs[i, :] = np.loadtxt(filename, skiprows=15 + 14 * i, max_rows=1, usecols=range(order + 1))

    # CurveXYZFourier wants data in order sin_x, cos_x, sin_y, cos_y, ...
    coil_data = np.zeros((order + 1, ncoils * 6))
    for i in range(ncoils):
        coil_data[:, i * 6 + 0] = xs[i, :]
        coil_data[:, i * 6 + 1] = xc[i, :]
        coil_data[:, i * 6 + 2] = ys[i, :]
        coil_data[:, i * 6 + 3] = yc[i, :]
        coil_data[:, i * 6 + 4] = zs[i, :]
        coil_data[:, i * 6 + 5] = zc[i, :]

    # Set the degrees of freedom in the coil objects
    base_currents = [Current(coilcurrents[i]) for i in range(ncoils)]
    ppp = 20
    coils = [CurveXYZFourier(order*ppp, order) for i in range(ncoils)]
    for ic in range(ncoils):
        dofs = coils[ic].dofs
        dofs[0][0] = coil_data[0, 6*ic + 1]
        dofs[1][0] = coil_data[0, 6*ic + 3]
        dofs[2][0] = coil_data[0, 6*ic + 5]
        for io in range(0, min(order, coil_data.shape[0]-1)):
            dofs[0][2*io+1] = coil_data[io+1, 6*ic + 0]
            dofs[0][2*io+2] = coil_data[io+1, 6*ic + 1]
            dofs[1][2*io+1] = coil_data[io+1, 6*ic + 2]
            dofs[1][2*io+2] = coil_data[io+1, 6*ic + 3]
            dofs[2][2*io+1] = coil_data[io+1, 6*ic + 4]
            dofs[2][2*io+2] = coil_data[io+1, 6*ic + 5]
        coils[ic].local_x = np.concatenate(dofs)
    return coils, base_currents, ncoils


def coil_optimization(s, bs, base_curves, curves, OUT_DIR, s_plot, config_flag):
    """
        Optimize the coils for the QA or QH configurations
    """
    nphi = len(s.quadpoints_phi)
    ntheta = len(s.quadpoints_theta)
    ncoils = len(base_curves)

    if 'QH' in config_flag:
        # Weight on the curve lengths in the objective function:
        LENGTH_WEIGHT = 1e-1

        # Threshold and weight for the coil-to-coil distance penalty in the objective function:
        CC_THRESHOLD = 0.5
        CC_WEIGHT = 1e3

        # Threshold and weight for the coil-to-surface distance penalty in the objective function:
        CS_THRESHOLD = 0.3
        CS_WEIGHT = 10

        # Threshold and weight for the curvature penalty in the objective function:
        CURVATURE_THRESHOLD = 1.
        CURVATURE_WEIGHT = 1e-6

        # Threshold and weight for the mean squared curvature penalty in the objective function:
        MSC_THRESHOLD = 1
        MSC_WEIGHT = 1e-6
    else: 
        # Weight on the curve lengths in the objective function:
        LENGTH_WEIGHT = 1e-4

        # Threshold and weight for the coil-to-coil distance penalty in the objective function:
        CC_THRESHOLD = 0.1
        CC_WEIGHT = 1e-1

        # Threshold and weight for the coil-to-surface distance penalty in the objective function:
        CS_THRESHOLD = 0.1
        CS_WEIGHT = 1e-2

        # Threshold and weight for the curvature penalty in the objective function:
        CURVATURE_THRESHOLD = 0.1
        CURVATURE_WEIGHT = 1e-9

        # Threshold and weight for the mean squared curvature penalty in the objective function:
        MSC_THRESHOLD = 0.1
        MSC_WEIGHT = 1e-9

    MAXITER = 500  # number of iterations for minimize

    # Define the objective function:
    Jf = SquaredFlux(s, bs)
    Jls = [CurveLength(c) for c in base_curves]
    Jccdist = CurveCurveDistance(curves, CC_THRESHOLD, num_basecurves=ncoils)
    Jcsdist = CurveSurfaceDistance(curves, s, CS_THRESHOLD)
    Jcs = [LpCurveCurvature(c, 2, CURVATURE_THRESHOLD) for c in base_curves]
    Jmscs = [MeanSquaredCurvature(c) for c in base_curves]

    # Form the total objective function.
    JF = Jf \
        + LENGTH_WEIGHT * sum(Jls) \
        + CC_WEIGHT * Jccdist \
        + CS_WEIGHT * Jcsdist \
        + CURVATURE_WEIGHT * sum(Jcs) \
        + MSC_WEIGHT * sum(QuadraticPenalty(J, MSC_THRESHOLD) for J in Jmscs)

    def fun(dofs):
        JF.x = dofs
        J = JF.J()
        grad = JF.dJ()
        jf = Jf.J()
        BdotN = np.mean(np.abs(np.sum(bs.B().reshape((nphi, ntheta, 3)) * s.unitnormal(), axis=2)))
        outstr = f"J={J:.1e}, Jf={jf:.1e}, ⟨B·n⟩={BdotN:.1e}"
        cl_string = ", ".join([f"{J.J():.1f}" for J in Jls])
        kap_string = ", ".join(f"{np.max(c.kappa()):.1f}" for c in base_curves)
        msc_string = ", ".join(f"{J.J():.1f}" for J in Jmscs)
        outstr += f", Len=sum([{cl_string}])={sum(J.J() for J in Jls):.1f}, ϰ=[{kap_string}], ∫ϰ²/L=[{msc_string}]"
        outstr += f", C-C-Sep={Jccdist.shortest_distance():.2f}, C-S-Sep={Jcsdist.shortest_distance():.2f}"
        outstr += f", ║∇J║={np.linalg.norm(grad):.1e}"
        print(outstr)
        return J, grad

    print("""
    ################################################################################
    ### Perform a Taylor test ######################################################
    ################################################################################
    """)
    f = fun
    dofs = JF.x
    np.random.seed(1)
    h = np.random.uniform(size=dofs.shape)

    J0, dJ0 = f(dofs)
    dJh = sum(dJ0 * h)
    for eps in [1e-3, 1e-4, 1e-5, 1e-6, 1e-7]:
        J1, _ = f(dofs + eps*h)
        J2, _ = f(dofs - eps*h)
        print("err", (J1-J2)/(2*eps) - dJh)

    print("""
    ################################################################################
    ### Run the optimisation #######################################################
    ################################################################################
    """)
    res = minimize(fun, dofs, jac=True, method='L-BFGS-B', options={'maxiter': MAXITER, 'maxcor': 300}, tol=1e-15)
    curves_to_vtk(curves, OUT_DIR + f"curves_opt")
    bs.set_points(s.gamma().reshape((-1, 3)))
    return s, bs


def read_regcoil_pm(filename, surface_filename, OUT_DIR):
    """
        Load in REGCOIL_PM solution for NCSX half-Tesla example. This
        is likely to have errors and need to double check this.
    """
    f = netcdf.netcdf_file(filename, 'r', mmap=False)
    nfp = f.variables['nfp'][()]
    ntheta_plasma = f.variables['ntheta_plasma'][()]
    ntheta_coil = f.variables['ntheta_coil'][()]
    nzeta_plasma = f.variables['nzeta_plasma'][()]
    nzeta_coil = f.variables['nzeta_coil'][()]
    nzetal_plasma = f.variables['nzetal_plasma'][()]
    nzetal_coil = f.variables['nzetal_coil'][()]
    zeta_coil = f.variables['zeta_coil'][()]
    zetal_coil = f.variables['zetal_coil'][()]
    r_coil = f.variables['r_coil'][()]
    chi2_B = f.variables['chi2_B'][()]
    print('chi2B = ', chi2_B)

    chi2_M = f.variables['chi2_M'][()]
    abs_M = f.variables['abs_M'][()]

    print('volume = ', f.variables['volume_magnetization'][()])
    d = f.variables['d'][()]
    Bnormal_from_TF_and_plasma_current = f.variables['Bnormal_from_TF_and_plasma_current'][()]
    max_Bnormal = f.variables['max_Bnormal'][()]
    print('REGCOIL_PM max Bnormal = ', max_Bnormal)
    Bnormal_total = f.variables['Bnormal_total'][()]
    Mvec = f.variables['magnetization_vector'][()]

    # Make a surface for plotting the solution
    quadpoints_phi = np.linspace(0, 1, nzetal_plasma, endpoint=True)
    quadpoints_theta = np.linspace(0, 1, ntheta_plasma, endpoint=True)
    s_plot = SurfaceRZFourier.from_wout(surface_filename, range="full torus", quadpoints_phi=quadpoints_phi, quadpoints_theta=quadpoints_theta)
    #s_plot = SurfaceRZFourier.from_focus(surface_filename, range="full torus", quadpoints_phi=quadpoints_phi, quadpoints_theta=quadpoints_theta)

    # Get Bnormal around the full torus and plot results
    Bnormal_TF = np.zeros((nzetal_plasma, ntheta_plasma))
    Bnormal = np.zeros((nzetal_plasma, ntheta_plasma))
    Bnormal_total = Bnormal_total[-1, :, :]
    for i in range(nfp):
        Bnormal_TF[i * nzeta_plasma:(i + 1) * nzeta_plasma, :] = Bnormal_from_TF_and_plasma_current
        Bnormal[i * nzeta_plasma:(i + 1) * nzeta_plasma, :] = Bnormal_total
    pointData = {"B_N": Bnormal_TF[:, :, None]}
    s_plot.to_vtk(OUT_DIR + "regcoil_pm_ncsx_TF", extra_data=pointData)
    pointData = {"B_N": Bnormal[:, :, None]}
    s_plot.to_vtk(OUT_DIR + "regcoil_pm_ncsx_total", extra_data=pointData)

    # Get the magnetization vectors and max magnetization 
    Mvec = Mvec[-1, :, :, :, :].reshape(3, nzeta_coil, ntheta_coil)
    m_maxima = np.ravel(abs_M[-1, :, :, :])
    print('Effective volume = ', np.sum(np.ravel(np.sqrt(np.sum(Mvec ** 2, axis=0))) / np.ravel(m_maxima)))
    Mvec_total = np.zeros((nzetal_coil, ntheta_coil, 3))

    # convert Mvec to cartesian
    for i in range(ntheta_coil):
        Mvec_x = Mvec[0, :, i] * np.cos(zeta_coil) - Mvec[1, :, i] * np.sin(zeta_coil)
        Mvec_y = Mvec[0, :, i] * np.sin(zeta_coil) + Mvec[1, :, i] * np.cos(zeta_coil)
        # somehow need to put in stellarator symmetry below...
        for fp in range(nfp):
            phi0 = (2 * np.pi / nfp) * fp
            Mvec_total[fp * nzeta_coil:(fp + 1) * nzeta_coil, i, 0] = Mvec_x * np.cos(phi0) - Mvec_y * np.sin(phi0)
            Mvec_total[fp * nzeta_coil:(fp + 1) * nzeta_coil, i, 1] = Mvec_x * np.sin(phi0) + Mvec_y * np.cos(phi0)
            Mvec_total[fp * nzeta_coil:(fp + 1) * nzeta_coil, i, 2] = Mvec[2, :, i]

    Mvec_total = Mvec_total.reshape(nzetal_coil * ntheta_coil, 3)
    Mvec = np.transpose(Mvec, [1, 2, 0]).reshape(nzeta_coil * ntheta_coil, 3)
    m_maxima = np.ravel(np.array([m_maxima, m_maxima, m_maxima]))

    # Make 3D vtk file of dipole vectors and locations
    # Ideally would like to have the individual volumes to convert
    # M -> m for comparison with other codes
    ox = np.ascontiguousarray(r_coil[:, :, 0])
    oy = np.ascontiguousarray(r_coil[:, :, 1])
    oz = np.ascontiguousarray(r_coil[:, :, 2])
    mx = np.ascontiguousarray(Mvec_total[:, 0])
    my = np.ascontiguousarray(Mvec_total[:, 1])
    mz = np.ascontiguousarray(Mvec_total[:, 2])
    mx_normalized = np.ascontiguousarray(mx / m_maxima)
    my_normalized = np.ascontiguousarray(my / m_maxima)
    mz_normalized = np.ascontiguousarray(mz / m_maxima)
    print("write VTK as points")
    data = {"m": (mx, my, mz), "m_normalized": (mx_normalized, my_normalized, mz_normalized)}
    pointsToVTK(
        OUT_DIR + "Dipole_Fields_REGCOIL_PM", ox, oy, oz, data=data
    )


def trace_fieldlines(bfield, label, config, s, comm): 
    """
        Make Poincare plots on a surface as in the trace_fieldlines
        example in the examples/1_Simple/ directory.
    """
    from simsopt.field.tracing import particles_to_vtk, compute_fieldlines, \
        LevelsetStoppingCriterion, plot_poincare_data, \
        IterationStoppingCriterion

    t1 = time.time()

    # set fieldline tracer parameters
    nfieldlines = 40
    tmax_fl = 30000

    # Different configurations have different cross-sections
    if config == 'muse':
        R0 = np.linspace(0.2, 0.4, nfieldlines)
    elif 'qa' in config: 
        R0 = np.linspace(0.5, 1.0, nfieldlines)
    elif 'qh' in config:
        R0 = np.linspace(0.5, 1.3, nfieldlines)
    elif config == 'ncsx': 
        R0 = np.linspace(1.0, 1.75, nfieldlines)
    elif config == 'QH':
        R0 = np.linspace(12.0, 18.0, nfieldlines)
    Z0 = np.zeros(nfieldlines)
    phis = [(i / 4) * (2 * np.pi / s.nfp) for i in range(4)]

    # compute the fieldlines from the initial locations specified above
    fieldlines_tys, fieldlines_phi_hits = compute_fieldlines(
        bfield, R0, Z0, tmax=tmax_fl, tol=1e-15, comm=comm,
        phis=phis, stopping_criteria=[IterationStoppingCriterion(200000)])
    t2 = time.time()
    print(f"Time for fieldline tracing={t2-t1:.3f}s. Num steps={sum([len(l) for l in fieldlines_tys])//nfieldlines}", flush=True)

    # make the poincare plots
    if comm is None or comm.rank == 0:
        particles_to_vtk(fieldlines_tys, OUT_DIR + f'fieldlines_{label}')
        plot_poincare_data(fieldlines_phi_hits, phis, OUT_DIR + f'poincare_fieldline_{label}.png', dpi=150)


def make_qfm(s, Bfield, Bfield_tf):
    """
        Given some Bfield generated by dipoles, and some Bfield_tf generated
        by a set of TF coils, compute a quadratic flux-minimizing surface (QFMS)
        for the total field configuration on the surface s. 
    """
    from simsopt.geo.qfmsurface import QfmSurface
    from simsopt.geo.surfaceobjectives import QfmResidual, ToroidalFlux, Area, Volume

    # weight for the optimization
    constraint_weight = 1e0

    # First optimize at fixed volume
    qfm = QfmResidual(s, Bfield)
    qfm.J()

    vol = Volume(s)
    vol_target = vol.J()
    qfm_surface = QfmSurface(Bfield, s, vol, vol_target)

    res = qfm_surface.minimize_qfm_penalty_constraints_LBFGS(tol=1e-12, maxiter=1000,
                                                             constraint_weight=constraint_weight)
    print(f"||vol constraint||={0.5*(s.volume()-vol_target)**2:.8e}, ||residual||={np.linalg.norm(qfm.J()):.8e}")

    res = qfm_surface.minimize_qfm_exact_constraints_SLSQP(tol=1e-12, maxiter=1000)
    print(f"||vol constraint||={0.5*(s.volume()-vol_target)**2:.8e}, ||residual||={np.linalg.norm(qfm.J()):.8e}")

    # Now optimize at fixed toroidal flux
    tf = ToroidalFlux(s, Bfield_tf)
    tf_target = tf.J()

    qfm_surface = QfmSurface(Bfield, s, tf, tf_target)

    res = qfm_surface.minimize_qfm_penalty_constraints_LBFGS(tol=1e-12, maxiter=1000,
                                                             constraint_weight=constraint_weight)
    print(f"||tf constraint||={0.5*(s.volume()-vol_target)**2:.8e}, ||residual||={np.linalg.norm(qfm.J()):.8e}")

    res = qfm_surface.minimize_qfm_exact_constraints_SLSQP(tol=1e-12, maxiter=1000)
    print(f"||tf constraint||={0.5*(tf.J()-tf_target)**2:.8e}, ||residual||={np.linalg.norm(qfm.J()):.8e}")

    # Check that volume is not changed
    print(f"||vol constraint||={0.5*(vol.J()-vol_target)**2:.8e}")

    # Now optimize at fixed area
    ar = Area(s)
    ar_target = ar.J()
    qfm_surface = QfmSurface(Bfield, s, ar, ar_target)

    res = qfm_surface.minimize_qfm_penalty_constraints_LBFGS(tol=1e-12, maxiter=1000, constraint_weight=constraint_weight)
    print(f"||area constraint||={0.5*(ar.J()-ar_target)**2:.8e}, ||residual||={np.linalg.norm(qfm.J()):.8e}")

    res = qfm_surface.minimize_qfm_exact_constraints_SLSQP(tol=1e-12, maxiter=1000)
    print(f"||area constraint||={0.5*(ar.J()-ar_target)**2:.8e}, ||residual||={np.linalg.norm(qfm.J()):.8e}")

    # Check that volume is not changed
    print(f"||vol constraint||={0.5*(vol.J()-vol_target)**2:.8e}")
    return qfm_surface.surface  # return QFMS