#include <memory>
#include <vector>
#include <functional>
#include "magneticfield.h"
#include "boozermagneticfield.h"
#include <cassert>
#include <stdexcept>
#include "tracing.h"
using std::shared_ptr;
using std::vector;
using std::tuple;
using std::pair;
using std::function;

#include "xtensor-python/pyarray.hpp"     // Numpy bindings
#include "xtensor-python/pytensor.hpp"     // Numpy bindings
typedef xt::pyarray<double> Array;

#include <boost/math/tools/roots.hpp>
#include <boost/numeric/odeint.hpp>
//#include <boost/numeric/odeint/stepper/bulirsch_stoer_dense_out.hpp>
using boost::math::tools::toms748_solve;
using namespace boost::numeric::odeint;

template<template<class, std::size_t, xt::layout_type> class T>
class GuidingCenterVacuumRHS {
    /*
     * The state consists of :math:`[x, y, z, v_par]` with
     *
     *   [\dot x, \dot y, \dot z] &= v_{||}\frac{B}{|B|} + \frac{m}{q|B|^3}  (0.5v_\perp^2 + v_{||}^2)  B\times \nabla(|B|)
     *   \dot v_{||}              &= -\mu  (B \cdot \nabla(|B|))
     *
     * where v_perp = 2*mu*|B|
     */
    private:
        std::array<double, 3> BcrossGradAbsB = {0., 0., 0.};
        typename MagneticField<T>::Tensor2 rphiz = xt::zeros<double>({1, 3});
        shared_ptr<MagneticField<T>> field;
        double m, q, mu;
    public:
        static constexpr int Size = 4;
        using State = std::array<double, Size>;
        static constexpr bool axis = false;

        GuidingCenterVacuumRHS(shared_ptr<MagneticField<T>> field, double m, double q, double mu)
            : field(field), m(m), q(q), mu(mu) {

            }

        void operator()(const State &ys, array<double, 4> &dydt,
                const double t) {
            double x = ys[0];
            double y = ys[1];
            double z = ys[2];
            double v_par = ys[3];

            rphiz(0, 0) = std::sqrt(x*x+y*y);
            rphiz(0, 1) = std::atan2(y, x);
            if(rphiz(0, 1) < 0)
                rphiz(0, 1) += 2*M_PI;
            rphiz(0, 2) = z;

            field->set_points_cyl(rphiz);
            auto& GradAbsB = field->GradAbsB_ref();
            auto& B = field->B_ref();
            double AbsB = field->AbsB_ref()(0);
            BcrossGradAbsB[0] = (B(0, 1) * GradAbsB(0, 2)) - (B(0, 2) * GradAbsB(0, 1));
            BcrossGradAbsB[1] = (B(0, 2) * GradAbsB(0, 0)) - (B(0, 0) * GradAbsB(0, 2));
            BcrossGradAbsB[2] = (B(0, 0) * GradAbsB(0, 1)) - (B(0, 1) * GradAbsB(0, 0));
            double v_perp2 = 2*mu*AbsB;
            double fak1 = (v_par/AbsB);
            double fak2 = (m/(q*pow(AbsB, 3)))*(0.5*v_perp2 + v_par*v_par);
            dydt[0] = fak1*B(0, 0) + fak2*BcrossGradAbsB[0];
            dydt[1] = fak1*B(0, 1) + fak2*BcrossGradAbsB[1];
            dydt[2] = fak1*B(0, 2) + fak2*BcrossGradAbsB[2];
            dydt[3] = -mu*(B(0, 0)*GradAbsB(0, 0) + B(0, 1)*GradAbsB(0, 1) + B(0, 2)*GradAbsB(0, 2))/AbsB;
        }
};




template<template<class, std::size_t, xt::layout_type> class T>
class GuidingCenterVacuumBoozerRHS {
    /*
     * The state consists of :math:`[s, t, z, v_par]` with
     *
     *    \dot s = -|B|_{,\theta} m(v_{||}^2/|B| + \mu)/(q \psi_0)
     *    \dot \theta = |B|_{,s} m(v_{||}^2/|B| + \mu)/(q \psi_0) + \iota v_{||} |B|/G
     *    \dot \zeta = v_{||}|B|/G
     *    \dot v_{||} = -(\iota |B|_{,\theta} + |B|_{,\zeta})\mu |B|/G,
     *
     *  where :math:`q` is the charge, :math:`m` is the mass, and :math:`v_\perp = 2\mu|B|`.
     *
     */
    private:
        typename BoozerMagneticField<T>::Tensor2 stz = xt::zeros<double>({1, 3});
        shared_ptr<BoozerMagneticField<T>> field;
        double m, q, mu;
    public:
        int axis;
        static constexpr int Size = 4;
        using State = std::array<double, Size>;

        GuidingCenterVacuumBoozerRHS(shared_ptr<BoozerMagneticField<T>> field, double m, double q, double mu, int axis)
            : field(field), m(m), q(q), mu(mu), axis(axis) {
            }

        void operator()(const State &ys, array<double, 4> &dydt,
                const double t) {
            double v_par = ys[3];
            double s, theta;
            if (axis==1) {
                s = pow(ys[0],2)+pow(ys[1],2);
                theta = atan2(ys[1],ys[0]);          
            } else if (axis==2) {
                s = sqrt(pow(ys[0],2)+pow(ys[1],2));
                theta = atan2(ys[1],ys[0]); 
            } else {
                s = ys[0];
                theta = ys[1];
            }  

            stz(0, 0) = s;
            stz(0, 1) = theta;
            stz(0, 2) = ys[2];

            field->set_points(stz);
            auto psi0 = field->psi0;
            double modB = field->modB_ref()(0);
            double G = field->G_ref()(0);
            double iota = field->iota_ref()(0);
            double dmodBds = field->modB_derivs_ref()(0);
            double dmodBdtheta = field->modB_derivs_ref()(1);
            double dmodBdzeta = field->modB_derivs_ref()(2);
            double v_perp2 = 2*mu*modB;
            double fak1 = m*v_par*v_par/modB + m*mu;

            double sdot = -dmodBdtheta*fak1/(q*psi0);
            double tdot = dmodBds*fak1/(q*psi0) + iota*v_par*modB/G; 

            if (axis==1) {
                dydt[0] = sdot*cos(theta)/(2*sqrt(s)) - sqrt(s) * sin(theta) * tdot;
                dydt[1] = sdot*sin(theta)/(2*sqrt(s)) + sqrt(s) * cos(theta) * tdot;
            } else if (axis==2) {
                dydt[0] = sdot*cos(theta) - s * sin(theta) * tdot;
                dydt[1] = sdot*sin(theta) + s * cos(theta) * tdot; 
            } else {
                dydt[0] = sdot;
                dydt[1] = tdot;
            }
            dydt[2] = v_par*modB/G;
            dydt[3] = -(iota*dmodBdtheta + dmodBdzeta)*mu*modB/G;
        }
};

template<template<class, std::size_t, xt::layout_type> class T>
class GuidingCenterVacuumBoozerPerturbedRHS {
    /*
     * The state consists of :math:`[s, t, z, v_par]` with
     *
     *    \dot s = -|B|_{,\theta} m(v_{||}^2/|B| + \mu)/(q \psi_0)
     *    \dot \theta = |B|_{,s} m(v_{||}^2/|B| + \mu)/(q \psi_0) + \iota v_{||} |B|/G
     *    \dot \zeta = v_{||}|B|/G
     *    \dot v_{||} = -(\iota |B|_{,\theta} + |B|_{,\zeta})\mu |B|/G,
     *
     *  where :math:`q` is the charge, :math:`m` is the mass, and :math:`v_\perp = 2\mu|B|`.
     *
     */
    private:
        typename BoozerMagneticField<T>::Tensor2 stz = xt::zeros<double>({1, 3});
        shared_ptr<BoozerMagneticField<T>> field;
        double m, q, mu, Phihat, omega, phase;
        int Phim, Phin;
    public:
        int axis;
        static constexpr int Size = 5;
        using State = std::array<double, Size>;

        GuidingCenterVacuumBoozerPerturbedRHS(shared_ptr<BoozerMagneticField<T>> field,
            double m, double q, double mu, double Phihat, double omega, int Phim,
            int Phin, double phase, int axis)
            : field(field), m(m), q(q), mu(mu), Phihat(Phihat), omega(omega),
              Phim(Phim), Phin(Phin), phase(phase), axis(axis) {
            }

        void operator()(const State &ys, array<double, 5> &dydt,
                const double t) {
            double v_par = ys[3];
            double time = ys[4];
            double s, theta;
            if (axis==1) {
                s = pow(ys[0],2)+pow(ys[1],2);
                theta = atan2(ys[1],ys[0]);          
            } else if (axis==2) {
                s = sqrt(pow(ys[0],2)+pow(ys[1],2));
                theta = atan2(ys[1],ys[0]); 
            } else {
                s = ys[0];
                theta = ys[1];
            }  

            stz(0, 0) = s;
            stz(0, 1) = theta;
            stz(0, 2) = ys[2];

            field->set_points(stz);
            auto psi0 = field->psi0;
            double modB = field->modB_ref()(0);
            double G = field->G_ref()(0);
            double iota = field->iota_ref()(0);
            double diotadpsi = field->diotads_ref()(0)/psi0;
            double dmodBdpsi = field->modB_derivs_ref()(0)/psi0;
            double dmodBdtheta = field->modB_derivs_ref()(1);
            double dmodBdzeta = field->modB_derivs_ref()(2);
            double v_perp2 = 2*mu*modB;
            double fak1 = m*v_par*v_par/modB + m*mu;
            double Phi = Phihat * sin(Phim * theta - Phin * ys[2] + omega * time + phase);
            double dPhidpsi = 0;
            double Phidot = Phihat * omega * cos(Phim * theta - Phin * ys[2] + omega * time + phase);
            double dPhidtheta = Phidot * Phim / omega;
            double dPhidzeta = - Phidot * Phin / omega;
            double alpha = - Phi * (iota*Phim - Phin)/(omega*G);
            double alphadot = - Phidot * (iota*Phim - Phin)/(omega*G);
            double dalphadtheta = - dPhidtheta * (iota*Phim - Phin)/(omega*G);
            double dalphadzeta = - dPhidzeta * (iota*Phim - Phin)/(omega*G);
            double dalphadpsi = - dPhidpsi * (iota*Phim - Phin)/(omega*G) \
                - Phi * (diotadpsi*Phim)/(omega*G);

            double sdot = (-dmodBdtheta*fak1/q + dalphadtheta*modB*v_par - dPhidtheta)/psi0;
            double tdot = dmodBdpsi*fak1/q + (iota - dalphadpsi*G)*v_par*modB/G + dPhidpsi;
            if (axis==1) {
                dydt[0] = sdot*cos(theta)/(2*sqrt(s)) - sqrt(s) * sin(theta) * tdot;
                dydt[1] = sdot*sin(theta)/(2*sqrt(s)) + sqrt(s) * cos(theta) * tdot;
            } else if (axis==2) {
                dydt[0] = sdot*cos(theta) - s * sin(theta) * tdot;
                dydt[1] = sdot*sin(theta) + s * cos(theta) * tdot; 
            } else {
                dydt[0] = sdot;
                dydt[1] = tdot;
            }
            dydt[2] = v_par*modB/G;
            dydt[3] = -modB/(G*m) * (m*mu*(dmodBdzeta + dalphadtheta*dmodBdpsi*G \
                    + dmodBdtheta*(iota - dalphadpsi*G)) + q*(alphadot*G \
                    + dalphadtheta*G*dPhidpsi + (iota - dalphadpsi*G)*dPhidtheta + dPhidzeta)) \
                    + v_par/modB * (dmodBdtheta*dPhidpsi - dmodBdpsi*dPhidtheta);
            dydt[4] = 1;
        }
};


template<template<class, std::size_t, xt::layout_type> class T>
class GuidingCenterNoKBoozerPerturbedRHS {
    /*
     * The state consists of :math:`[s, t, z, v_par]` with
     *
     *    \dot s = -|B|_{,\theta} m(v_{||}^2/|B| + \mu)/(q \psi_0)
     *    \dot \theta = |B|_{,s} m(v_{||}^2/|B| + \mu)/(q \psi_0) + \iota v_{||} |B|/G
     *    \dot \zeta = v_{||}|B|/G
     *    \dot v_{||} = -(\iota |B|_{,\theta} + |B|_{,\zeta})\mu |B|/G,
     *
     *  where :math:`q` is the charge, :math:`m` is the mass, and :math:`v_\perp = 2\mu|B|`.
     *
     */
    private:
        typename BoozerMagneticField<T>::Tensor2 stz = xt::zeros<double>({1, 3});
        shared_ptr<BoozerMagneticField<T>> field;
        double m, q, mu, Phihat, omega, phase;
        int Phim, Phin;
    public:
        int axis;
        static constexpr int Size = 5;
        using State = std::array<double, Size>;

        GuidingCenterNoKBoozerPerturbedRHS(shared_ptr<BoozerMagneticField<T>> field,
            double m, double q, double mu, double Phihat, double omega, int Phim,
            int Phin, double phase, int axis)
            : field(field), m(m), q(q), mu(mu), Phihat(Phihat), omega(omega),
              Phim(Phim), Phin(Phin), phase(phase), axis(axis) {
            }

        void operator()(const State &ys, array<double, 5> &dydt,
                const double t) {
            double v_par = ys[3];
            double time = ys[4];
            double s, theta;
            if (axis==1) {
                s = pow(ys[0],2)+pow(ys[1],2);
                theta = atan2(ys[1],ys[0]);          
            } else if (axis==2) {
                s = sqrt(pow(ys[0],2)+pow(ys[1],2));
                theta = atan2(ys[1],ys[0]); 
            } else {
                s = ys[0];
                theta = ys[1];
            }  

            stz(0, 0) = s;
            stz(0, 1) = theta;
            stz(0, 2) = ys[2];

            field->set_points(stz);
            auto psi0 = field->psi0;
            double modB = field->modB_ref()(0);
            double G = field->G_ref()(0);
            double I = field->I_ref()(0);
            double dGdpsi = field->dGds_ref()(0)/psi0;
            double dIdpsi = field->dIds_ref()(0)/psi0;
            double iota = field->iota_ref()(0);
            double diotadpsi = field->diotads_ref()(0)/psi0;
            double dmodBdpsi = field->modB_derivs_ref()(0)/psi0;
            double dmodBdtheta = field->modB_derivs_ref()(1);
            double dmodBdzeta = field->modB_derivs_ref()(2);
            double v_perp2 = 2*mu*modB;
            double fak1 = m*v_par*v_par/modB + m*mu;
            double Phi = Phihat * sin(Phim * theta - Phin * ys[2] + omega * time + phase);
            double dPhidpsi = 0;
            double Phidot = Phihat * omega * cos(Phim * theta - Phin * ys[2] + omega * time + phase);
            double dPhidtheta = Phidot * Phim / omega;
            double dPhidzeta = - Phidot * Phin / omega;
            double alpha = - Phi * (iota*Phim - Phin)/(omega*(G+iota*I));
            double alphadot = - Phidot * (iota*Phim - Phin)/(omega*(G+iota*I));
            double dalphadtheta = - dPhidtheta * (iota*Phim - Phin)/(omega*(G+iota*I));
            double dalphadzeta = -dPhidzeta * (iota*Phim - Phin)/(omega*(G+iota*I));
            double dalphadpsi = - dPhidpsi * (iota*Phim - Phin)/(omega*(G+iota*I)) \
                - (Phi/omega) * (diotadpsi*Phim/(G+iota*I) \
                - (iota*Phim - Phin)/((G+iota*I)*(G+iota*I)) * (dGdpsi + diotadpsi*I + iota*dIdpsi));
            double denom = q*(G + I*(-alpha*dGdpsi + iota) + alpha*G*dIdpsi) + m*v_par/modB * (-dGdpsi*I + G*dIdpsi); // q G in vacuum

            double sdot = (-G*dPhidtheta*q + I*dPhidzeta*q + modB*q*v_par*(dalphadtheta*G-dalphadzeta*I) + (-dmodBdtheta*G + dmodBdzeta*I)*fak1)/(denom*psi0);
            double tdot = (G*q*dPhidpsi + modB*q*v_par*(-dalphadpsi*G - alpha*dGdpsi + iota) - dGdpsi*m*v_par*v_par \
                      + dmodBdpsi*G*fak1)/denom;
            if (axis==1) {
                dydt[0] = sdot*cos(theta)/(2*sqrt(s)) - sqrt(s) * sin(theta) * tdot;
                dydt[1] = sdot*sin(theta)/(2*sqrt(s)) + sqrt(s) * cos(theta) * tdot;
            } else if (axis==2) {
                dydt[0] = sdot*cos(theta) - s * sin(theta) * tdot;
                dydt[1] = sdot*sin(theta) + s * cos(theta) * tdot; 
            } else {
                dydt[0] = sdot;
                dydt[1] = tdot;
            }
            dydt[2] = (-I*(dmodBdpsi*m*mu + dPhidpsi*q) + modB*q*v_par*(1 + dalphadpsi*I + alpha*dIdpsi) \
                      + m*v_par*v_par/modB * (modB*dIdpsi - dmodBdpsi*I))/denom;
            dydt[3] = (modB*q/m * ( -m*mu * (dmodBdzeta*(1 + dalphadpsi*I + alpha*dIdpsi) \
                      + dmodBdpsi*(dalphadtheta*G - dalphadzeta*I) + dmodBdtheta*(iota - alpha*dGdpsi - dalphadpsi*G)) \
                      - q*(alphadot*(G + I*(iota - alpha*dGdpsi) + alpha*G*dIdpsi) \
                      + (dalphadtheta*G - dalphadzeta*I)*dPhidpsi \
                      + (iota - alpha*dGdpsi - dalphadpsi*G)*dPhidtheta \
                      + (1 + alpha*dIdpsi + dalphadpsi*I)*dPhidzeta)) \
                      + q*v_par/modB * ((dmodBdtheta*G - dmodBdzeta*I)*dPhidpsi \
                      + dmodBdpsi*(I*dPhidzeta - G*dPhidtheta)) \
                      + v_par*(m*mu*(dmodBdtheta*dGdpsi - dmodBdzeta*dIdpsi) \
                      + q*(alphadot*(dGdpsi*I-G*dIdpsi) + dGdpsi*dPhidtheta - dIdpsi*dPhidzeta)))/denom;
            dydt[4] = 1;
        }
};

template<template<class, std::size_t, xt::layout_type> class T>
class GuidingCenterNoKBoozerRHS {
    /*
     * The state consists of :math:`[s, t, z, v_par]` with
     *
     *  \dot s = (I |B|_{,\zeta} - G |B|_{,\theta})m(v_{||}^2/|B| + \mu)/(\iota D \psi_0)
     *  \dot \theta = (G |B|_{,\psi} m(v_{||}^2/|B| + \mu) - (-q \iota + m v_{||} G' / |B|) v_{||} |B|)/(\iota D)
     *  \dot \zeta = \left((q + m v_{||} I'/|B|) v_{||} |B| - |B|_{,\psi} m(\rho_{||}^2 |B| + \mu) I\right)/(\iota D)
     *  \dot v_{||} = ((-q\iota + m v_{||} G'/|B|)|B|_{,\theta} - (q + m v_{||}I'/|B|)|B|_{,\zeta})\mu |B|/(\iota D)
     *  D = ((q + m v_{||} I'/|B|)*G - (-q \iota + m v_{||} G'/|B|) I)/\iota
     *
     *  where primes indicate differentiation wrt :math:`\psi`, :math:`q` is the charge,
     *  :math:`m` is the mass, and :math:`v_\perp = 2\mu|B|`. This corresponds
     *  with the limit K = 0.
     */
    private:
        typename BoozerMagneticField<T>::Tensor2 stz = xt::zeros<double>({1, 3});
        shared_ptr<BoozerMagneticField<T>> field;
        double m, q, mu;
    public:
        int axis;
        static constexpr int Size = 4;
        using State = std::array<double, Size>;


        GuidingCenterNoKBoozerRHS(shared_ptr<BoozerMagneticField<T>> field, double m, double q, double mu, int axis)
            : field(field), m(m), q(q), mu(mu), axis(axis) {
            }

        void operator()(const State &ys, array<double, 4> &dydt,
                const double t) {
            double v_par = ys[3];
            double s, theta;
            if (axis==1) {
                s = pow(ys[0],2)+pow(ys[1],2);
                theta = atan2(ys[1],ys[0]);          
            } else if (axis==2) {
                s = sqrt(pow(ys[0],2)+pow(ys[1],2));
                theta = atan2(ys[1],ys[0]); 
            } else {
                s = ys[0];
                theta = ys[1];
            }  

            stz(0, 0) = s;
            stz(0, 1) = theta;
            stz(0, 2) = ys[2];

            field->set_points(stz);
            auto psi0 = field->psi0;
            double modB = field->modB_ref()(0);
            double G = field->G_ref()(0);
            double I = field->I_ref()(0);
            double dGdpsi = field->dGds_ref()(0)/psi0;
            double dIdpsi = field->dIds_ref()(0)/psi0;
            double iota = field->iota_ref()(0);
            double dmodBdpsi = field->modB_derivs_ref()(0)/psi0;
            double dmodBdtheta = field->modB_derivs_ref()(1);
            double dmodBdzeta = field->modB_derivs_ref()(2);
            double v_perp2 = 2*mu*modB;
            double fak1 = m*v_par*v_par/modB + m*mu;
            double D = ((q + m*v_par*dIdpsi/modB)*G - (-q*iota + m*v_par*dGdpsi/modB)*I)/iota;

            double sdot = (I*dmodBdzeta - G*dmodBdtheta)*fak1/(D*iota*psi0);
            double tdot = (G*dmodBdpsi*fak1 - (-q*iota + m*v_par*dGdpsi/modB)*v_par*modB)/(D*iota);
            if (axis==1) {
                dydt[0] = sdot*cos(theta)/(2*sqrt(s)) - sqrt(s) * sin(theta) * tdot;
                dydt[1] = sdot*sin(theta)/(2*sqrt(s)) + sqrt(s) * cos(theta) * tdot;
            } else if (axis==2) {
                dydt[0] = sdot*cos(theta) - s * sin(theta) * tdot;
                dydt[1] = sdot*sin(theta) + s * cos(theta) * tdot; 
            } else {
                dydt[0] = sdot;
                dydt[1] = tdot;
            }
            dydt[2] = ((q + m*v_par*dIdpsi/modB)*v_par*modB - dmodBdpsi*fak1*I)/(D*iota);
            dydt[3] = - (mu / v_par) * (dmodBdpsi * sdot * psi0 + dmodBdtheta * tdot + dmodBdzeta * dydt[2]);
        }
};

template<template<class, std::size_t, xt::layout_type> class T>
class GuidingCenterBoozerRHS {
    /*
     * The state consists of :math:`[s, t, z, v_par]` with
     *
     *  \dot s = (I |B|_{,\zeta} - G |B|_{,\theta})m(v_{||}^2/|B| + \mu)/(\iota D \psi_0)
     *  \dot \theta = ((G |B|_{,\psi} - K |B|_{,\zeta}) m(v_{||}^2/|B| + \mu) - C v_{||} |B|)/(\iota D)
     *  \dot \zeta = (F v_{||} |B| - (|B|_{,\psi} I - |B|_{,\theta} K) m(\rho_{||}^2 |B| + \mu) )/(\iota D)
     *  \dot v_{||} = (C|B|_{,\theta} - F|B|_{,\zeta})\mu |B|/(\iota D)
     *  C = - m v_{||} K_{,\zeta}/|B|  - q \iota + m v_{||}G'/|B|
     *  F = - m v_{||} K_{,\theta}/|B| + q + m v_{||}I'/|B|
     *  D = (F G - C I))/\iota
     *
     *  where primes indicate differentiation wrt :math:`\psi`, :math:`q` is the charge,
     *  :math:`m` is the mass, and :math:`v_\perp = 2\mu|B|`.
     */
    private:
        typename BoozerMagneticField<T>::Tensor2 stz = xt::zeros<double>({1, 3});
        shared_ptr<BoozerMagneticField<T>> field;
        double m, q, mu;
    public:
        static constexpr int Size = 4;
        using State = std::array<double, Size>;
        int axis;

        GuidingCenterBoozerRHS(shared_ptr<BoozerMagneticField<T>> field, double m, double q, double mu, int axis)
            : field(field), m(m), q(q), mu(mu), axis(axis) {
            }

        void operator()(const State &ys, array<double, 4> &dydt,
                const double t) {
            double v_par = ys[3];
            double s, theta;
            if (axis==1) {
                s = pow(ys[0],2)+pow(ys[1],2);
                theta = atan2(ys[1],ys[0]);          
            } else if (axis==2) {
                s = sqrt(pow(ys[0],2)+pow(ys[1],2));
                theta = atan2(ys[1],ys[0]); 
            } else {
                s = ys[0];
                theta = ys[1];
            }  
            stz(0, 0) = s;
            stz(0, 1) = theta;
            stz(0, 2) = ys[2];

            field->set_points(stz);
            auto psi0 = field->psi0;
            double modB = field->modB_ref()(0);
            double K = field->K_ref()(0);
            double dKdtheta = field->K_derivs_ref()(0);
            double dKdzeta = field->K_derivs_ref()(1);

            double G = field->G_ref()(0);
            double I = field->I_ref()(0);
            double dGdpsi = field->dGds_ref()(0)/psi0;
            double dIdpsi = field->dIds_ref()(0)/psi0;
            double iota = field->iota_ref()(0);
            double dmodBdpsi = field->modB_derivs_ref()(0)/psi0;
            double dmodBdtheta = field->modB_derivs_ref()(1);
            double dmodBdzeta = field->modB_derivs_ref()(2);
            double v_perp2 = 2*mu*modB;
            double fak1 = m*v_par*v_par/modB + m*mu; // dHdB
            double C = -m*v_par*(dKdzeta-dGdpsi)/modB - q*iota;
            double F = -m*v_par*(dKdtheta-dIdpsi)/modB + q;
            double D = (F*G-C*I)/iota;

            double sdot = (I*dmodBdzeta - G*dmodBdtheta)*fak1/(D*iota*psi0);
            double tdot = (G*dmodBdpsi*fak1 - C*v_par*modB - K*fak1*dmodBdzeta)/(D*iota);
            if (axis==1) {
                dydt[0] = sdot*cos(theta)/(2*sqrt(s)) - sqrt(s) * sin(theta) * tdot;
                dydt[1] = sdot*sin(theta)/(2*sqrt(s)) + sqrt(s) * cos(theta) * tdot;
            } else if (axis==2) {
                dydt[0] = sdot*cos(theta) - s * sin(theta) * tdot;
                dydt[1] = sdot*sin(theta) + s * cos(theta) * tdot; 
            } else {
                dydt[0] = sdot;
                dydt[1] = tdot;
            }
            dydt[2] = (F*v_par*modB - dmodBdpsi*fak1*I + K*fak1*dmodBdtheta)/(D*iota);
            dydt[3] = - (mu / v_par) * (dmodBdpsi * sdot * psi0 + dmodBdtheta * tdot + dmodBdzeta * dydt[2]);
        }
};

template<template<class, std::size_t, xt::layout_type> class T>
class FullorbitRHS {
    // Right hand side for full orbit tracing of particles, the state is
    // (x, y, z, \dot x, \dot y, \dot z) and the rhs is
    // (\dot x, \dot y, \dot z, \dot\dot x, \dot\dot y, \dot\dot z).
    // Using F=m*a and F = q * v \cross B, we get a = (q/m) * v\cross B
    // and hence \dot\dot (x, y, z) = (q/m)* \dot(x,y,z) \cross B
    // where we used v = \dot (x,y,z)
    private:
        typename MagneticField<T>::Tensor2 rphiz = xt::zeros<double>({1, 6});
        shared_ptr<MagneticField<T>> field;
        const double qoverm;
    public:
        static constexpr int Size = 6;
        using State = std::array<double, Size>;
        static constexpr bool axis = false;

        FullorbitRHS(shared_ptr<MagneticField<T>> field, double m, double q)
            : field(field), qoverm(q/m) {

            }
        void operator()(const array<double, 6> &ys, array<double, 6> &dydt,
                const double t) {
            double x = ys[0];
            double y = ys[1];
            double z = ys[2];
            double vx = ys[3];
            double vy = ys[4];
            double vz = ys[5];
            rphiz(0, 0) = std::sqrt(x*x+y*y);
            rphiz(0, 1) = std::atan2(y, x);
            if(rphiz(0, 1) < 0)
                rphiz(0, 1) += 2*M_PI;
            rphiz(0, 2) = z;
            field->set_points_cyl(rphiz);
            auto& B = field->B_ref();
            double Bx = B(0, 0);
            double By = B(0, 1);
            double Bz = B(0, 2);
            dydt[0] = vx;
            dydt[1] = vy;
            dydt[2] = vz;
            dydt[3] = qoverm * (vy*Bz-vz*By);
            dydt[4] = qoverm * (vz*Bx-vx*Bz);
            dydt[5] = qoverm * (vx*By-vy*Bx);
        }
};
template<template<class, std::size_t, xt::layout_type> class T>
class FieldlineRHS {
    private:
        typename MagneticField<T>::Tensor2 rphiz = xt::zeros<double>({1, 3});
        shared_ptr<MagneticField<T>> field;
    public:
        static constexpr int Size = 3;
        using State = std::array<double, Size>;
        static constexpr bool axis = false;

        FieldlineRHS(shared_ptr<MagneticField<T>> field)
            : field(field) {

            }
        void operator()(const array<double, 3> &ys, array<double, 3> &dydt,
                const double t) {
            double x = ys[0];
            double y = ys[1];
            double z = ys[2];
            rphiz(0, 0) = std::sqrt(x*x+y*y);
            rphiz(0, 1) = std::atan2(y, x);
            if(rphiz(0, 1) < 0)
                rphiz(0, 1) += 2*M_PI;
            rphiz(0, 2) = z;
            field->set_points_cyl(rphiz);
            auto& B = field->B_ref();
            dydt[0] = B(0, 0);
            dydt[1] = B(0, 1);
            dydt[2] = B(0, 2);
        }
};

double get_phi(double x, double y, double phi_near){
    double phi = std::atan2(y, x);
    if(phi < 0)
        phi += 2*M_PI;
    double phi_near_mod = std::fmod(phi_near, 2*M_PI);
    double nearest_multiple = std::round(phi_near/(2*M_PI))*2*M_PI;
    double opt1 = nearest_multiple - 2*M_PI + phi;
    double opt2 = nearest_multiple + phi;
    double opt3 = nearest_multiple + 2*M_PI + phi;
    double dist1 = std::abs(opt1-phi_near);
    double dist2 = std::abs(opt2-phi_near);
    double dist3 = std::abs(opt3-phi_near);
    if(dist1 <= std::min(dist2, dist3))
        return opt1;
    else if(dist2 <= std::min(dist1, dist3))
        return opt2;
    else
        return opt3;
}

template<std::size_t m, std::size_t n>
std::array<double, m+n> join(const std::array<double, m>& a, const std::array<double, n>& b){
     std::array<double, m+n> res;
     for (int i = 0; i < m; ++i) {
         res[i] = a[i];
     }
     for (int i = 0; i < n; ++i) {
         res[i+m] = b[i];
     }
     return res;
}



template<class RHS>
tuple<vector<array<double, RHS::Size+1>>, vector<array<double, RHS::Size+2>>>
solve(RHS rhs, typename RHS::State y, double tmax, double dt, double dtmax, double abstol, double reltol,
    vector<double> phis, vector<double> omegas, vector<shared_ptr<StoppingCriterion>> stopping_criteria,
    vector<double> vpars, bool phis_stop=false, bool vpars_stop=false, bool flux=false,
    bool forget_exact_path=false) {
    vector<array<double, RHS::Size+1>> res = {};
    vector<array<double, RHS::Size+2>> res_phi_hits = {};
    array<double, RHS::Size> ykeep = {};
    typedef typename RHS::State State;
    typedef typename boost::numeric::odeint::result_of::make_dense_output<runge_kutta_dopri5<State>>::type dense_stepper_type;
    dense_stepper_type dense = make_dense_output(abstol, reltol, dtmax, runge_kutta_dopri5<State>());
    double t = 0;
    dense.initialize(y, t, dt);
    int iter = 0;
    bool stop = false;
    double phi_last;
    double vpar_last = 0;
    double t_last = 0;
    if (flux) {
      t_last = t;
      phi_last = y[2];
      vpar_last = y[3];
    } else {
      phi_last = get_phi(y[0], y[1], M_PI);
    }
    double phi_current, vpar_current, t_current;
    boost::math::tools::eps_tolerance<double> roottol(-int(std::log2(abstol)));
    uintmax_t rootmaxit = 200;
    State temp;
    do {
        if (!forget_exact_path || t==0) {
            ykeep = y;
            if (rhs.axis==1) {
                ykeep[0] = pow(y[0],2) + pow(y[1],2);
                ykeep[1] = atan2(y[1],y[0]);
            } else if (rhs.axis==2) {
                ykeep[0] = sqrt(pow(y[0],2) + pow(y[1],2));
                ykeep[1] = atan2(y[1],y[0]);
            }
            res.push_back(join<1, RHS::Size>({t}, ykeep));
        }
        tuple<double, double> step = dense.do_step(rhs);
        iter++;
        t = dense.current_time();
        y = dense.current_state();
        if (flux) {
          t_current = t;
          phi_current = y[2];
          vpar_current = y[3];
      } else {
          phi_current = get_phi(y[0], y[1], phi_last);
      }
        double tlast = std::get<0>(step);
        double tcurrent = std::get<1>(step);
        dt = tcurrent - tlast;
        // Now check whether we have hit any of the vpar planes
        for (int i = 0; i < vpars.size(); ++i) {
            double vpar = vpars[i];
            if( (vpar_last-vpar != 0) && (vpar_current-vpar != 0) && (((vpar_last-vpar > 0) ? 1 : ((vpar_last-vpar < 0) ? -1 : 0)) != ((vpar_current-vpar > 0) ? 1 : ((vpar_current-vpar < 0) ? -1 : 0)))){ // check whether vpar = vpars[i] was crossed
                std::function<double(double)> rootfun = [&dense, &temp, &vpar_last, &vpar](double t){
                    dense.calc_state(t, temp);
                    return temp[3]-vpar;
                };
                auto root = toms748_solve(rootfun, tlast, tcurrent, vpar_last-vpar, vpar_current-vpar, roottol, rootmaxit);
                double f0 = rootfun(root.first);
                double f1 = rootfun(root.second);
                double troot = std::abs(f0) < std::abs(f1) ? root.first : root.second;
                dense.calc_state(troot, temp);
                ykeep = temp;
                if (rhs.axis==1) {
                    ykeep[0] = pow(temp[0],2) + pow(temp[1],2);
                    ykeep[1] = atan2(temp[1],temp[0]);
                } else if (rhs.axis==2) {
                    ykeep[0] = sqrt(pow(temp[0],2) + pow(temp[1],2));
                    ykeep[1] = atan2(temp[1],temp[0]);
                }
                res_phi_hits.push_back(join<2, RHS::Size>({troot, double(i) + phis.size()}, ykeep));
                if (vpars_stop) {
                    res.push_back(join<1, RHS::Size>({troot}, ykeep));
                    stop = true;
                    break;
                }
            }
        }
        // Now check whether we have hit any of the (phi - omega t) planes
        for (int i = 0; i < phis.size(); ++i) {
            double phi = phis[i];
            double omega = omegas[i];
            double phase_last = phi_last - omega*t_last;
            double phase_current = phi_current - omega*t_current;
            if(t_last!=0 && (std::floor((phase_last-phi)/(2*M_PI)) != std::floor((phase_current-phi)/(2*M_PI)))) { // check whether phi+k*2pi for some k was crossed
                int fak = std::round(((phase_last+phase_current)/2-phi)/(2*M_PI));
                double phase_shift = fak*2*M_PI + phi;
                assert((phase_last <= phase_shift && phase_shift <= phase_current) || (phase_current <= phase_shift && phase_shift <= phase_last));

                std::function<double(double)> rootfun = [&phase_shift, &phi_last, &omega, &dense, &temp, &flux](double t){
                    dense.calc_state(t, temp);
                    if (flux) {
                      return temp[2] - omega*t - phase_shift;
                    } else {
                      return get_phi(temp[0], temp[1], phi_last) - omega*t - phase_shift;
                    }
                };
                auto root = toms748_solve(rootfun, tlast, tcurrent, phase_last - phase_shift, phase_current - phase_shift, roottol, rootmaxit);
                double f0 = rootfun(root.first);
                double f1 = rootfun(root.second);
                double troot = std::abs(f0) < std::abs(f1) ? root.first : root.second;
                dense.calc_state(troot, temp);
                ykeep = temp;
                if (rhs.axis==1) {
                    ykeep[0] = pow(temp[0],2) + pow(temp[1],2);
                    ykeep[1] = atan2(temp[1],temp[0]);
                } else if (rhs.axis==2) {
                    ykeep[0] = sqrt(pow(temp[0],2) + pow(temp[1],2));
                    ykeep[1] = atan2(temp[1],temp[0]);
                }
                res_phi_hits.push_back(join<2, RHS::Size>({troot, double(i)}, ykeep));
                if (phis_stop) {
                    res.push_back(join<1, RHS::Size>({troot}, ykeep));
                    stop = true;
                    break;
                }
            }
        }
        // check whether we have satisfied any of the extra stopping criteria (e.g. left a surface)
        for (int i = 0; i < stopping_criteria.size(); ++i) {
            ykeep = y;
            if (rhs.axis==1) {
                ykeep[0] = pow(y[0],2) + pow(y[1],2);
                ykeep[1] = atan2(y[1],y[0]);
            } else if (rhs.axis==2) {
                ykeep[0] = sqrt(pow(y[0],2) + pow(y[1],2));
                ykeep[1] = atan2(y[1],y[0]);
            }
            if(stopping_criteria[i] && (*stopping_criteria[i])(iter, dt, t, ykeep[0], ykeep[1], ykeep[2], ykeep[3])){
                stop = true;
                res.push_back(join<1, RHS::Size>({t}, ykeep));
                res_phi_hits.push_back(join<2, RHS::Size>({t, -1-double(i)}, ykeep));
                break;
            }
        }
        t_last = t_current;
        phi_last = phi_current;
        vpar_last = vpar_current;
    } while(t < tmax && !stop);
    if(!stop){
        dense.calc_state(tmax, y);
        ykeep = y;
        if (rhs.axis==1) {
            ykeep[0] = pow(y[0],2) + pow(y[1],2);
            ykeep[1] = atan2(y[1],y[0]);
        } else if (rhs.axis==2) {
            ykeep[0] = sqrt(pow(y[0],2) + pow(y[1],2));
            ykeep[1] = atan2(y[1],y[0]);
        }      
        res.push_back(join<1, RHS::Size>({tmax}, ykeep));
    }
    return std::make_tuple(res, res_phi_hits);
}



template<template<class, std::size_t, xt::layout_type> class T>
tuple<vector<array<double, 5>>, vector<array<double, 6>>>
particle_guiding_center_tracing(
        shared_ptr<MagneticField<T>> field, array<double, 3> xyz_init,
        double m, double q, double vtotal, double vtang, double tmax, double abstol, double reltol, bool vacuum,
        vector<double> phis, vector<double> omegas, vector<shared_ptr<StoppingCriterion>> stopping_criteria)
{
    typename MagneticField<T>::Tensor2 xyz({{xyz_init[0], xyz_init[1], xyz_init[2]}});
    field->set_points(xyz);
    double AbsB = field->AbsB_ref()(0);
    double vperp2 = vtotal*vtotal - vtang*vtang;
    double mu = vperp2/(2*AbsB);

    array<double, 4> y = {xyz_init[0], xyz_init[1], xyz_init[2], vtang};
    double r0 = std::sqrt(xyz_init[0]*xyz_init[0] + xyz_init[1]*xyz_init[1]);
    double dtmax = r0*0.5*M_PI/vtotal; // can at most do quarter of a revolution per step
    double dt = 1e-3 * dtmax; // initial guess for first timestep, will be adjusted by adaptive timestepper

    if(vacuum){
        auto rhs_class = GuidingCenterVacuumRHS<T>(field, m, q, mu);
        return solve(rhs_class, y, tmax, dt, dtmax, abstol, reltol, phis, omegas, stopping_criteria, {});
    }
    else
        throw std::logic_error("Guiding center right hand side currently only implemented for vacuum fields.");
}

template<template<class, std::size_t, xt::layout_type> class T>
tuple<vector<array<double, 6>>, vector<array<double, 7>>>
particle_guiding_center_boozer_perturbed_tracing(
        shared_ptr<BoozerMagneticField<T>> field, array<double, 3> stz_init,
        double m, double q, double vtotal, double vtang, double mu, double tmax, double abstol, double reltol,
        bool vacuum, bool noK, vector<double> zetas, vector<double> omegas,
        vector<shared_ptr<StoppingCriterion>> stopping_criteria, vector<double> vpars,
        bool phis_stop, bool vpars_stop, double Phihat, double omega, int Phim,
        int Phin, double phase, bool forget_exact_path, int axis)
{
    typename BoozerMagneticField<T>::Tensor2 stz({{stz_init[0], stz_init[1], stz_init[2]}});
    field->set_points(stz);
    double modB = field->modB()(0);
    array<double, 5> y;
    double G0 = std::abs(field->G()(0));
    double r0 = G0/modB;
    double dtmax = r0*0.5*M_PI/vtotal; // can at most do quarter of a revolution per step
    double dt = 1e-3 * dtmax; // initial guess for first timestep, will be adjusted by adaptive timestepper
    
    if (axis==1) {
      y = {sqrt(stz_init[0]) * cos(stz_init[1]), sqrt(stz_init[0]) * sin(stz_init[1]), stz_init[2], vtang, 0};
    } else if (axis==2) {
      y = {stz_init[0] * cos(stz_init[1]), stz_init[0] * sin(stz_init[1]), stz_init[2], vtang, 0};
    } else {
      y = {stz_init[0], stz_init[1], stz_init[2], vtang, 0};
    }
    if (vacuum) {
      auto rhs_class = GuidingCenterVacuumBoozerPerturbedRHS<T>(field, m, q, mu, Phihat, omega,
        Phim, Phin, phase, axis);
      return solve(rhs_class, y, tmax, dt, dtmax, abstol, reltol, zetas, omegas, stopping_criteria,
        vpars, phis_stop, vpars_stop, true, forget_exact_path);
  } else {
      auto rhs_class = GuidingCenterNoKBoozerPerturbedRHS<T>(field, m, q, mu, Phihat, omega,
        Phim, Phin, phase, axis);
      return solve(rhs_class, y, tmax, dt, dtmax, abstol, reltol, zetas, omegas, stopping_criteria,
        vpars, phis_stop, vpars_stop, true, forget_exact_path);
  }
}

template<template<class, std::size_t, xt::layout_type> class T>
tuple<vector<array<double, 5>>, vector<array<double, 6>>>
particle_guiding_center_boozer_tracing(
        shared_ptr<BoozerMagneticField<T>> field, array<double, 3> stz_init,
        double m, double q, double vtotal, double vtang, double tmax, double abstol, double reltol,
        bool vacuum, bool noK, vector<double> zetas, vector<double> omegas,
        vector<shared_ptr<StoppingCriterion>> stopping_criteria, vector<double> vpars,
        bool phis_stop, bool vpars_stop, bool forget_exact_path, int axis)
{
    typename BoozerMagneticField<T>::Tensor2 stz({{stz_init[0], stz_init[1], stz_init[2]}});
    field->set_points(stz);
    double modB = field->modB()(0);
    double vperp2 = vtotal*vtotal - vtang*vtang;
    double mu = vperp2/(2*modB);

    array<double, 4> y;
    double G0 = std::abs(field->G()(0));
    double r0 = G0/modB;
    double dtmax = r0*0.5*M_PI/vtotal; // can at most do quarter of a revolution per step
    double dt = 1e-3 * dtmax; // initial guess for first timestep, will be adjusted by adaptive timestepper

    if (axis==1) {
      y = {sqrt(stz_init[0]) * cos(stz_init[1]), sqrt(stz_init[0]) * sin(stz_init[1]), stz_init[2], vtang};
    } else if (axis==2) {
      y = {stz_init[0] * cos(stz_init[1]), stz_init[0] * sin(stz_init[1]), stz_init[2], vtang};
    } else {
      y = {stz_init[0], stz_init[1], stz_init[2], vtang};
    }
    if (vacuum) {
      auto rhs_class = GuidingCenterVacuumBoozerRHS<T>(field, m, q, mu, axis);
      return solve(rhs_class, y, tmax, dt, dtmax, abstol, reltol, zetas, omegas, stopping_criteria,
        vpars, phis_stop, vpars_stop, true, forget_exact_path);
    } else if (noK) {
      auto rhs_class = GuidingCenterNoKBoozerRHS<T>(field, m, q, mu, axis);
      return solve(rhs_class, y, tmax, dt, dtmax, abstol, reltol, zetas, omegas, stopping_criteria,
        vpars, phis_stop, vpars_stop, true, forget_exact_path);
    } else {
      auto rhs_class = GuidingCenterBoozerRHS<T>(field, m, q, mu, axis);
      return solve(rhs_class, y, tmax, dt, dtmax, abstol, reltol, zetas, omegas, stopping_criteria,
        vpars, phis_stop, vpars_stop, true, forget_exact_path);
    }

}

template
tuple<vector<array<double, 6>>, vector<array<double, 7>>> particle_guiding_center_boozer_perturbed_tracing<xt::pytensor>(
        shared_ptr<BoozerMagneticField<xt::pytensor>> field, array<double, 3> stz_init,
        double m, double q, double vtotal, double vtang, double mu, double tmax, double abstol, double reltol,
        bool vacuum, bool noK, vector<double> zetas, vector<double> omegas,
        vector<shared_ptr<StoppingCriterion>> stopping_criteria,
        vector<double> vpars={}, bool phis_stop, bool vpars_stop, double Phihat,
        double omega, int Phim, int Phin, double phase, bool forget_exact_path, int axis);

template
tuple<vector<array<double, 5>>, vector<array<double, 6>>> particle_guiding_center_boozer_tracing<xt::pytensor>(
        shared_ptr<BoozerMagneticField<xt::pytensor>> field, array<double, 3> stz_init,
        double m, double q, double vtotal, double vtang, double tmax, double abstol, double reltol,
        bool vacuum, bool noK, vector<double> zetas, vector<double> omegas,
        vector<shared_ptr<StoppingCriterion>> stopping_criteria,
        vector<double> vpars={}, bool phis_stop, bool vpars_stop, bool forget_exact_path, int axis);

template
tuple<vector<array<double, 5>>, vector<array<double, 6>>> particle_guiding_center_tracing<xt::pytensor>(
        shared_ptr<MagneticField<xt::pytensor>> field, array<double, 3> xyz_init,
        double m, double q, double vtotal, double vtang, double tmax, double abstol, double reltol, bool vacuum,
        vector<double> phis, vector<double> omegas, vector<shared_ptr<StoppingCriterion>> stopping_criteria);


template<template<class, std::size_t, xt::layout_type> class T>
tuple<vector<array<double, 7>>, vector<array<double, 8>>>
particle_fullorbit_tracing(
        shared_ptr<MagneticField<T>> field, array<double, 3> xyz_init, array<double, 3> v_init,
        double m, double q, double tmax, double abstol, double reltol, vector<double> phis, vector<shared_ptr<StoppingCriterion>> stopping_criteria)
{

    auto rhs_class = FullorbitRHS<T>(field, m, q);
    array<double, 6> y = {xyz_init[0], xyz_init[1], xyz_init[2], v_init[0], v_init[1], v_init[2]};

    double vtotal = std::sqrt(std::pow(v_init[0], 2) + std::pow(v_init[1], 2) + std::pow(v_init[2], 2));
    double r0 = std::sqrt(xyz_init[0]*xyz_init[0] + xyz_init[1]*xyz_init[1]);
    double dtmax = r0*0.5*M_PI/vtotal; // can at most do quarter of a revolution per step
    double dt = 1e-3 * dtmax; // initial guess for first timestep, will be adjusted by adaptive timestepper
    vector<double> omegas(phis.size(), 0);
    return solve(rhs_class, y, tmax, dt, dtmax, abstol, reltol, phis, omegas, stopping_criteria, {});
}

template
tuple<vector<array<double, 7>>, vector<array<double, 8>>> particle_fullorbit_tracing<xt::pytensor>(
        shared_ptr<MagneticField<xt::pytensor>> field, array<double, 3> xyz_init, array<double, 3> v_init,
        double m, double q, double tmax, double abstol, double reltol, vector<double> phis, vector<shared_ptr<StoppingCriterion>> stopping_criteria);

template<template<class, std::size_t, xt::layout_type> class T>
tuple<vector<array<double, 4>>, vector<array<double, 5>>>
fieldline_tracing(
    shared_ptr<MagneticField<T>> field, array<double, 3> xyz_init,
    double tmax, double abstol, double reltol, vector<double> phis, vector<shared_ptr<StoppingCriterion>> stopping_criteria)
{
    auto rhs_class = FieldlineRHS<T>(field);
    double r0 = std::sqrt(xyz_init[0]*xyz_init[0] + xyz_init[1]*xyz_init[1]);
    typename MagneticField<T>::Tensor2 xyz({{xyz_init[0], xyz_init[1], xyz_init[2]}});
    field->set_points(xyz);
    double AbsB = field->AbsB_ref()(0);
    double dtmax = r0*0.5*M_PI/AbsB; // can at most do quarter of a revolution per step
    double dt = 1e-5 * dtmax; // initial guess for first timestep, will be adjusted by adaptive timestepper
    vector<double> omegas(phis.size(), 0);
    return solve(rhs_class, xyz_init, tmax, dt, dtmax, abstol, reltol, phis, omegas, stopping_criteria, {});
}

template
tuple<vector<array<double, 4>>, vector<array<double, 5>>>
fieldline_tracing(
    shared_ptr<MagneticField<xt::pytensor>> field, array<double, 3> xyz_init,
    double tmax, double abstol, double reltol, vector<double> phis, vector<shared_ptr<StoppingCriterion>> stopping_criteria);
