from math import pi
import numpy as np
from simsopt.geo.biotsavart import BiotSavart
from simsopt.geo.surfacexyzfourier import SurfaceXYZFourier
from simsopt.geo.surfacerzfourier import SurfaceRZFourier
from simsopt.geo.curve import RotatedCurve
from simsopt.geo.curverzfourier import CurveRZFourier 
from simsopt.geo.curvexyzfourier import CurveXYZFourier 
from simsopt.geo.surfaceobjectives import ToroidalFlux 
import os
from pathlib import Path
TEST_DIR = (Path(__file__).parent / ".." / "test_files").resolve()


class CoilCollection():
    """
    Given some input coils and currents, this performs the reflection and
    rotation to generate a full set of stellarator coils.
    """

    def __init__(self, coils, currents, nfp, stellarator_symmetry):
        self._base_coils = coils
        self._base_currents = currents
        self.coils = []
        self.currents = []
        flip_list = [False, True] if stellarator_symmetry else [False] 
        self.map = []
        self.current_sign = []
        for k in range(0, nfp):
            for flip in flip_list:
                for i in range(len(coils)):
                    if k == 0 and not flip:
                        self.coils.append(self._base_coils[i])
                        self.currents.append(self._base_currents[i])
                    else:
                        rotcoil = RotatedCurve(coils[i], 2*pi*k/nfp, flip)
                        self.coils.append(rotcoil)
                        self.currents.append(-self._base_currents[i] if flip else currents[i])
                    self.map.append(i)
                    self.current_sign.append(-1 if flip else +1)
        dof_ranges = [(0, len(self._base_coils[0].get_dofs()))]
        for i in range(1, len(self._base_coils)):
            dof_ranges.append((dof_ranges[-1][1], dof_ranges[-1][1] + len(self._base_coils[i].get_dofs())))
        self.dof_ranges = dof_ranges

def get_ncsx_data(Nt_coils=25, Nt_ma=10, ppp=10):
    filename = os.path.join(TEST_DIR, 'NCSX_test_data/NCSX_coil_coeffs.dat')
    coil_data = np.loadtxt(filename, delimiter=',')
    nfp = 3
    num_coils = 3
    coils = [CurveXYZFourier(Nt_coils*ppp, Nt_coils) for i in range(num_coils)]
    for ic in range(num_coils):
        dofs = coils[ic].dofs
        dofs[0][0] = coil_data[0, 6*ic + 1]
        dofs[1][0] = coil_data[0, 6*ic + 3]
        dofs[2][0] = coil_data[0, 6*ic + 5]
        for io in range(0, Nt_coils):
            dofs[0][2*io+1] = coil_data[io+1, 6*ic + 0]
            dofs[0][2*io+2] = coil_data[io+1, 6*ic + 1]
            dofs[1][2*io+1] = coil_data[io+1, 6*ic + 2]
            dofs[1][2*io+2] = coil_data[io+1, 6*ic + 3]
            dofs[2][2*io+1] = coil_data[io+1, 6*ic + 4]
            dofs[2][2*io+2] = coil_data[io+1, 6*ic + 5]
        coils[ic].set_dofs(np.concatenate(dofs))

    currents = [6.52271941985300E+05, 6.51868569367400E+05, 5.37743588647300E+05]
#    currents = [c/1.474 for c in currents] # normalise to get a magnetic field of around 1 at the axis
    cR = [1.471415400740515, 0.1205306261840785, 0.008016125223436036, -0.000508473952304439, -0.0003025251710853062, -0.0001587936004797397, 3.223984137937924e-06, 3.524618949869718e-05, 2.539719080181871e-06, -9.172247073731266e-06, -5.9091166854661e-06, -2.161311017656597e-06, -5.160802127332585e-07, -4.640848016990162e-08, 2.649427979914062e-08, 1.501510332041489e-08, 3.537451979994735e-09, 3.086168230692632e-10, 2.188407398004411e-11, 5.175282424829675e-11, 1.280947310028369e-11, -1.726293760717645e-11, -1.696747733634374e-11, -7.139212832019126e-12, -1.057727690156884e-12, 5.253991686160475e-13]
    sZ = [0.06191774986623827, 0.003997436991295509, -0.0001973128955021696, -0.0001892615088404824, -2.754694372995494e-05, -1.106933185883972e-05, 9.313743937823742e-06, 9.402864564707521e-06, 2.353424962024579e-06, -1.910411249403388e-07, -3.699572817752344e-07, -1.691375323357308e-07, -5.082041581362814e-08, -8.14564855367364e-09, 1.410153957667715e-09, 1.23357552926813e-09, 2.484591855376312e-10, -3.803223187770488e-11, -2.909708414424068e-11, -2.009192074867161e-12, 1.775324360447656e-12, -7.152058893039603e-13, -1.311461207101523e-12, -6.141224681566193e-13, -6.897549209312209e-14]

    numpoints = Nt_ma*ppp+1 if ((Nt_ma*ppp) % 2 == 0) else Nt_ma*ppp
    ma = CurveRZFourier(numpoints, Nt_ma, nfp, True)
    ma.rc[:] = cR[0:(Nt_ma+1)]
    ma.zs[:] = sZ[0:Nt_ma]
    return (coils, currents, ma)

def get_surface(surfacetype, stellsym, phis=None, thetas=None):
    nfp = 3
    ntor = 5
    mpol = 5
    nphi = 15
    ntheta = 15 
    
    if phis is None:
        phis = np.linspace(0, 1/nfp, nphi, endpoint=False)
    if thetas is None:
        thetas = np.linspace(0, 1/(1. + (stellsym == True)), ntheta, endpoint=False)
    
    if surfacetype == "SurfaceXYZFourier":
        s = SurfaceXYZFourier(mpol=mpol, ntor=ntor, nfp = nfp, stellsym=stellsym, quadpoints_phi = phis, quadpoints_theta = thetas)
    elif surfacetype == "SurfaceRZFourier":
        s = SurfaceRZFourier(mpol=mpol, ntor=ntor, nfp = nfp, stellsym=stellsym, quadpoints_phi = phis, quadpoints_theta = thetas)
    else:
        raise "surface type not implemented"
    return s

def get_exact_surface():
    filename_X = os.path.join(TEST_DIR, 'NCSX_test_data/X.dat')
    filename_Y = os.path.join(TEST_DIR, 'NCSX_test_data/Y.dat')
    filename_Z = os.path.join(TEST_DIR, 'NCSX_test_data/Z.dat')
    X = np.loadtxt(filename_X)
    Y = np.loadtxt(filename_Y)
    Z = np.loadtxt(filename_Z)
    xyz = np.concatenate( (X[:,:, None] ,  Y[:,:,None], Z[:,:, None]), axis = 2) 
    ntor = 16 
    mpol = 10
    
    nfp = 1
    stellsym = False
    nphi = 33
    ntheta = 21
    
    phis = np.linspace(0, 1, nphi, endpoint=False)
    thetas = np.linspace(0, 1, ntheta, endpoint=False)
    s = SurfaceXYZFourier(mpol=mpol, ntor=ntor, nfp = nfp, stellsym=stellsym, quadpoints_phi = phis, quadpoints_theta = thetas)
    s.least_squares_fit(xyz)
    return s

