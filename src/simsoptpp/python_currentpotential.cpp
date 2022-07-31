#include "pybind11/pybind11.h"
#include "pybind11/stl.h"
#include "xtensor-python/pyarray.hpp"
typedef xt::pyarray<double> PyArray;
using std::shared_ptr;
using std::vector;

namespace py = pybind11;
#include "currentpotential.h"
#include "pycurrentpotential.h"
#include "pysurface.h"
#include "surface.h"
#include "currentpotentialfourier.h"
typedef CurrentPotentialFourier<PyArray> PyCurrentPotentialFourier;

template <class PyCurrentPotentialFourierBase = PyCurrentPotentialFourier> class PyCurrentPotentialFourierTrampoline : public PyCurrentPotentialTrampoline<PyCurrentPotentialFourierBase> {
    public:
        using PyCurrentPotentialTrampoline<PyCurrentPotentialFourierBase>::PyCurrentPotentialTrampoline;
        using PyCurrentPotentialFourierBase::mpol;
        using PyCurrentPotentialFourierBase::ntor;
        using PyCurrentPotentialFourierBase::nfp;
        using PyCurrentPotentialFourierBase::stellsym;

        int num_dofs() override {
            return PyCurrentPotentialFourierBase::num_dofs();
        }

        void set_dofs_impl(const vector<double>& _dofs) override {
            PyCurrentPotentialFourierBase::set_dofs_impl(_dofs);
        }

        vector<double> get_dofs() override {
            return PyCurrentPotentialFourierBase::get_dofs();
        }

        void Phi_impl(PyArray& data, PyArray& quadpoints_phi, PyArray& quadpoints_theta) override {
            PyCurrentPotentialFourierBase::Phi_impl(data, quadpoints_phi, quadpoints_theta);
        }

        void Phidash1_impl(PyArray& data) override {
            PyCurrentPotentialFourierBase::Phidash1_impl(data);
        }

        void Phidash2_impl(PyArray& data) override {
            PyCurrentPotentialFourierBase::Phidash2_impl(data);
        }
};

template <typename T, typename S> void register_common_currentpotential_methods(S &s) {
    s.def("Phi", &T::Phi)
     .def("Phi", &T::Phi_impl)
     .def("Phidash1", &T::Phidash1)
     .def("Phidash2", &T::Phidash2)
     .def("invalidate_cache", &T::invalidate_cache)
     .def("set_dofs", &T::set_dofs)
     .def("set_dofs_impl", &T::set_dofs_impl)
     .def("get_dofs", &T::get_dofs)
     .def_readonly("quadpoints_phi", &T::quadpoints_phi)
     .def_readonly("quadpoints_theta", &T::quadpoints_theta);
}

void init_currentpotential(py::module_ &m){
    auto pycurrentpotential = py::class_<PyCurrentPotential, shared_ptr<PyCurrentPotential>, PyCurrentPotentialTrampoline<PyCurrentPotential>>(m, "CurrentPotential")
        .def(py::init<shared_ptr<PySurface>,vector<double>,vector<double>>());
        // .def(py::init<vector<double>,vector<double>>());
    register_common_currentpotential_methods<PyCurrentPotential>(pycurrentpotential);

    auto pycurrentpotentialfourier = py::class_<PyCurrentPotentialFourier, shared_ptr<PyCurrentPotentialFourier>, PyCurrentPotentialFourierTrampoline<PyCurrentPotentialFourier>>(m, "CurrentPotentialFourier")
        // .def(py::init<int, int, int, bool, vector<double>, vector<double>>())
        .def(py::init<shared_ptr<PySurface>, int, int, int, bool, vector<double>, vector<double>>())
        .def_readwrite("phic", &PyCurrentPotentialFourier::phic)
        .def_readwrite("phis", &PyCurrentPotentialFourier::phis)
        .def_readwrite("mpol", &PyCurrentPotentialFourier::mpol)
        .def_readwrite("ntor", &PyCurrentPotentialFourier::ntor)
        .def_readwrite("nfp", &PyCurrentPotentialFourier::nfp)
        .def_readwrite("stellsym", &PyCurrentPotentialFourier::stellsym)
        .def("allocate", &PyCurrentPotentialFourier::allocate);
    register_common_currentpotential_methods<PyCurrentPotentialFourier>(pycurrentpotentialfourier);
}