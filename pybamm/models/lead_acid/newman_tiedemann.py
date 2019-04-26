#
# Lead-acid Porous-Electrode model
#
from __future__ import absolute_import, division
from __future__ import print_function, unicode_literals
import pybamm


class NewmanTiedemann(pybamm.LeadAcidBaseModel):
    """Porous electrode model for lead-acid, from [1]_.

    .. math::
        \\frac{\\partial \\tilde{c}}{\\partial t}
        = \\frac{1}{\\varepsilon^{(0)}}\\left(
            \\frac{D^{\\text{eff}, (0)}}{\\mathcal{C}_\\text{e}}
            \\frac{\\partial^2 \\tilde{c}}{\\partial x^2}
            + \\left(
                s + \\beta^{\\text{surf}}c^{(0)}
            \\right)j^{(0)}
        \\right)


    **Notation for variables and parameters:**

    * f_xy means :math:`f^{(x)}_\\text{y}` (x is the power for the asymptotic \
    expansion and y is the domain). For example c_1n means :math:`c^{(1)}_\\text{n}`, \
    the first-order concentration in the negative electrode
    * fbar_n means :math:`\\bar{f}_n`, the average value of f in that domain, e.g.

    .. math::
        \\text{cbar_n}
        = \\bar{c}_\\text{n}
        = \\frac{1}{\\ell_\\text{n}}
        \\int_0^{\\ell_\\text{n}} \\! c_\\text{n} \\, \\mathrm{d}x

    **Extends:** :class:`pybamm.LeadAcidBaseModel`

    References
    ==========
    .. [1] V Sulzer, SJ Chapman, CP Please, DA Howey, and CW Monroe. Faster Lead-Acid
           Battery Simulations from Porous-Electrode Theory: I. Physical Model.
           arXiv preprint arXiv:1902.01771, 2019.

    """

    def __init__(self):
        super().__init__()

        "-----------------------------------------------------------------------------"
        "Parameters"
        param = pybamm.standard_parameters_lead_acid

        "-----------------------------------------------------------------------------"
        "Model Variables"

        c_e = pybamm.standard_variables.c_e
        eps = pybamm.standard_variables.eps
        phi_e = pybamm.standard_variables.phi_e
        phi_s_p = pybamm.standard_variables.phi_s_p
        phi_s_n = pybamm.standard_variables.phi_s_n

        "-----------------------------------------------------------------------------"
        "Submodels"
        # Exchange-current density
        c_e_n, _, c_e_p = c_e.orphans
        int_curr_model = pybamm.interface.LeadAcidReaction(param)
        j0_n = int_curr_model.get_exchange_current_densities(c_e_n)
        j0_p = int_curr_model.get_exchange_current_densities(c_e_p)

        # Potentials
        phi_e_n, _, phi_e_p = phi_e.orphans
        ocp_n = param.U_n(c_e_n)
        ocp_p = param.U_p(c_e_p)
        eta_r_n = phi_s_n - phi_e_n - ocp_n
        eta_r_p = phi_s_p - phi_e_p - ocp_p

        # Interfacial current density
        j_n = int_curr_model.get_butler_volmer(j0_n, eta_r_n)
        j_p = int_curr_model.get_butler_volmer(j0_p, eta_r_p)

        # Porosity
        porosity_model = pybamm.porosity.Standard(param)
        porosity_model.set_differential_system(eps, j_n, j_p)

        # Electrolyte concentration
        reactions = {
            "main": {
                "neg": {"s_plus": param.s_n, "aj": j_n},
                "pos": {"s_plus": param.s_p, "aj": j_p},
                "porosity change": porosity_model.variables["Porosity change"],
            }
        }
        # Electrolyte diffusion model
        electrolyte_diffusion_model = pybamm.electrolyte_diffusion.StefanMaxwell(param)
        electrolyte_diffusion_model.set_differential_system(c_e, reactions, eps)

        eleclyte_current_model = pybamm.electrolyte_current.MacInnesStefanMaxwell(param)
        eleclyte_current_model.set_algebraic_system(phi_e, c_e, reactions, eps)

        # Electrode models
        eps_n, _, eps_p = eps.orphans
        negative_electrode_current_model = pybamm.electrode.Ohm(param)
        negative_electrode_current_model.set_algebraic_system(phi_s_n, reactions, eps_n)
        positive_electrode_current_model = pybamm.electrode.Ohm(param)
        positive_electrode_current_model.set_algebraic_system(phi_s_p, reactions, eps_p)

        "-----------------------------------------------------------------------------"
        "Combine Submodels"
        self.update(
            porosity_model,
            electrolyte_diffusion_model,
            eleclyte_current_model,
            negative_electrode_current_model,
            positive_electrode_current_model,
        )

        "-----------------------------------------------------------------------------"
        "Post-process"

        # Excahnge-current density
        j_vars = int_curr_model.get_derived_interfacial_currents(j_n, j_p, j0_n, j0_p)
        self.variables.update(j_vars)

        # Potentials
        pot_model = pybamm.potential.Potential(param)
        ocp_vars = pot_model.get_derived_open_circuit_potentials(ocp_n, ocp_p)
        eta_r_vars = pot_model.get_derived_reaction_overpotentials(eta_r_n, eta_r_p)
        self.variables.update({**ocp_vars, **eta_r_vars})

        # Voltage
        phi_s_n = self.variables["Negative electrode potential"]
        phi_s_p = self.variables["Positive electrode potential"]
        i_s_n = self.variables["Negative electrode current density"]
        i_s_p = self.variables["Positive electrode current density"]
        volt_vars = positive_electrode_current_model.get_post_processed(
            phi_s_n, phi_s_p, i_s_n, i_s_p
        )
        self.variables.update(volt_vars)

        "-----------------------------------------------------------------------------"
        "Defaults and Solver Conditions"
        # default geometry
        self.default_geometry = pybamm.Geometry("1D macro", "1+1D micro")
        # Default solver to DAE
        self.default_solver = pybamm.ScikitsDaeSolver()
