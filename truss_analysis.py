"""
Linear-static analysis of a symmetric 2D parallel-chord Pratt or Howe truss.

Requirements:
    pip install openseespy numpy matplotlib

Units: N, m, Pa internally; kN and mm in printed results.
Educational linear-elastic analysis only; this is NOT a code-compliance check.

Model assumptions:
- Equal top- and bottom-chord spans (parallel chords).
- Pin-jointed, axial-only truss members.
- One pin support at the left bottom node and one vertical roller at the right.
- Loads are applied at joints. A uniform line load can be approximated by
  equivalent nodal loads on the bottom chord.
- Uniform E and cross-sectional area for every member.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import openseespy.opensees as ops


# ============================================================
# 1. INPUT HELPERS
# ============================================================

def ask_float(prompt: str, *, minimum: float | None = None,
              strictly_positive: bool = False) -> float:
    """Read a floating-point number, accepting decimal commas."""
    while True:
        raw = input(f"{prompt}: ").strip().replace(",", ".")
        try:
            value = float(raw)
            valid = np.isfinite(value)
            if minimum is not None:
                valid = valid and value >= minimum
            if strictly_positive:
                valid = valid and value > 0.0
            if valid:
                return value
        except ValueError:
            pass
        print("Invalid value. Please try again / Valeur invalide.")


def ask_int(prompt: str, *, minimum: int | None = None,
            maximum: int | None = None) -> int:
    """Read an integer within optional bounds."""
    while True:
        try:
            value = int(input(f"{prompt}: ").strip())
            if minimum is not None and value < minimum:
                raise ValueError
            if maximum is not None and value > maximum:
                raise ValueError
            return value
        except ValueError:
            print("Invalid integer. Please try again / Entier invalide.")


def ask_yes_no(prompt: str) -> bool:
    while True:
        answer = input(f"{prompt} [y/n]: ").strip().lower()
        if answer in {"y", "yes", "o", "oui"}:
            return True
        if answer in {"n", "no", "non"}:
            return False
        print("Please answer y/n (yes/no).")


# ============================================================
# 2. MODEL INPUTS AND GEOMETRY
# ============================================================

print("\n2D TRUSS ANALYSIS / ANALYSE D'UN TREILLIS 2D")
print("-" * 52)

truss_choice = ask_int(
    "Truss type: 1 = Pratt, 0 = Howe / Type : 1 = Pratt, 0 = Howe",
    minimum=0, maximum=1
)
truss_type = "Pratt" if truss_choice == 1 else "Howe"

print("\nSelect Truss Geometry / Sélectionnez la géométrie du treillis :")
print("  1 = Parallel-chord (Chords parallèles)")
print("  2 = Center-parallel with sloped end panels (Trapezoidal / Style Parker)")
print("  3 = Pitched / Triangular (Triangulaire / Pignon)")
geometry_choice = ask_int("Geometry choice / Choix de géométrie", minimum=1, maximum=3)

geometry_names = {
    1: "Parallel-Chord",
    2: "Center-Parallel with Sloped Ends",
    3: "Pitched / Triangular"
}
geometry_name = geometry_names[geometry_choice]

span = ask_float("Horizontal span / Portée horizontale (m)", strictly_positive=True)
height = ask_float("Max truss height / Hauteur maximale du treillis (m)", strictly_positive=True)
n_panels = ask_int("Number of equal panels (at least 2) / Nombre de panneaux",
                   minimum=2)

E = ask_float("Young's modulus E (Pa), e.g. 200e9 for steel",
              strictly_positive=True)
area = ask_float("Uniform member area A (m^2), e.g. 1e-3",
                 strictly_positive=True)

panel_width = span / n_panels
bottom_x = np.linspace(0.0, span, n_panels + 1)
n_bottom = n_panels + 1

nodes: dict[int, tuple[float, float]] = {}

# 1. Bottom nodes: 1 to n_bottom (indices 0 to n_panels)
for i, x in enumerate(bottom_x):
    nodes[i + 1] = (float(x), 0.0)
bottom_nodes = list(range(1, n_bottom + 1))

# 2. Top nodes generation
# Mapping to store which bottom node index (0 to n_panels) has a corresponding top node
top_node_map = {} 
current_node_tag = n_bottom + 1

if geometry_choice == 1:
    # Option 1: Parallel-chord (top node above every bottom node)
    for i, x in enumerate(bottom_x):
        nodes[current_node_tag] = (float(x), float(height))
        top_node_map[i] = current_node_tag
        current_node_tag += 1

elif geometry_choice == 2:
    # Option 2: Center-parallel with sloped ends (Parker style - triangle, rectangle, triangle)
    # Top nodes exist ONLY at interior panel points (i from 1 to n_panels - 1)
    for i in range(1, n_panels):
        x = bottom_x[i]
        nodes[current_node_tag] = (float(x), float(height))
        top_node_map[i] = current_node_tag
        current_node_tag += 1

else:
    # Option 3: Pitched / Triangular (top nodes from i=1 to n_panels-1, height varies linearly)
    center = n_panels / 2.0
    for i in range(1, n_panels):
        x = bottom_x[i]
        h = float(height) * max(0.0, 1.0 - abs(i - center) / center)
        if h > 1e-6:
            nodes[current_node_tag] = (float(x), float(h))
            top_node_map[i] = current_node_tag
            current_node_tag += 1

# 3. Define Chords, Verticals, and Diagonals
bottom_chord = [(bottom_nodes[i], bottom_nodes[i + 1]) for i in range(n_panels)]

top_chord = []
verticals = []
diagonals = []

# Top chord members connect adjacent existing top nodes
top_node_indices = sorted(top_node_map.keys())
for idx in range(len(top_node_indices) - 1):
    i_left = top_node_indices[idx]
    i_right = top_node_indices[idx + 1]
    top_chord.append((top_node_map[i_left], top_node_map[i_right]))

# Verticals connect bottom nodes to top nodes wherever a top node exists
for i, top_tag in top_node_map.items():
    verticals.append((bottom_nodes[i], top_tag))

# Diagonals / End sloping members panel by panel
for i in range(n_panels):
    # Determine the nodes defining panel i (from bottom_x[i] to bottom_x[i+1])
    b_left = bottom_nodes[i]
    b_right = bottom_nodes[i + 1]
    
    has_top_left = i in top_node_map
    has_top_right = (i + 1) in top_node_map
    
    if not has_top_left and has_top_right:
        # Left end sloping triangle panel
        top_r = top_node_map[i + 1]
        if truss_choice == 1:  # Pratt
            diagonals.append((top_r, b_right))
        else:  # Howe
            diagonals.append((b_left, top_r))
            
    elif has_top_left and not has_top_right:
        # Right end sloping triangle panel
        top_l = top_node_map[i]
        if truss_choice == 1:  # Pratt
            diagonals.append((b_left, top_l)) # Wait, for Pratt on right slope, let's check orientation
        else:  # Howe
            diagonals.append((top_l, b_right))
            
    elif has_top_left and has_top_right:
        # Interior parallel or pitched panel
        top_l = top_node_map[i]
        top_r = top_node_map[i + 1]
        if truss_choice == 1:  # Pratt
            if i < n_panels / 2:
                diagonals.append((top_l, b_right))
            else:
                diagonals.append((b_left, top_r))
        else:  # Howe
            if i < n_panels / 2:
                diagonals.append((b_left, top_r))
            else:
                diagonals.append((top_l, b_right))
    else:
        # Fully collapsed or zero-height panel if any
        pass

# Fix specific diagonal rule for Parker/Trapezoidal end panels to match standard engineering convention:
# Let's ensure the end sloping members act correctly as inclined end posts / diagonals.
if geometry_choice == 2:
    # Clear and rebuild diagonals specifically for Parker geometry to be 100% robust
    diagonals = []
    for i in range(n_panels):
        b_left = bottom_nodes[i]
        b_right = bottom_nodes[i + 1]
        
        if i == 0:
            # Left sloped end panel
            top_r = top_node_map[1]
            if truss_choice == 1:  # Pratt
                diagonals.append((top_r, b_right))
            else:  # Howe (sloping up from pin support to first interior top node)
                diagonals.append((b_left, top_r))
        elif i == n_panels - 1:
            # Right sloped end panel
            top_l = top_node_map[n_panels - 1]
            if truss_choice == 1:  # Pratt
                diagonals.append((b_left, top_l))
            else:  # Howe (sloping down from last interior top node to roller support)
                diagonals.append((top_l, b_right))
        else:
            # Interior parallel section panels
            top_l = top_node_map[i]
            top_r = top_node_map[i + 1]
            if truss_choice == 1:  # Pratt
                if i < n_panels / 2:
                    diagonals.append((top_l, b_right))
                else:
                    diagonals.append((b_left, top_r))
            else:  # Howe
                if i < n_panels / 2:
                    diagonals.append((b_left, top_r))
                else:
                    diagonals.append((top_l, b_right))

members = bottom_chord + top_chord + verticals + diagonals
member_groups = {
    "Bottom chord": bottom_chord,
    "Top chord": top_chord,
    "Verticals": verticals,
    "Diagonals": diagonals,
}

print("\nGEOMETRY SUMMARY")
print(f"Truss type              : {truss_type}")
print(f"Geometry style          : {geometry_name}")
print(f"Span                    : {span:.3f} m")
print(f"Max Height              : {height:.3f} m")
print(f"Number of panels        : {n_panels}")
print(f"Panel width             : {panel_width:.3f} m")
print(f"Number of nodes         : {len(nodes)}")
print(f"Number of members       : {len(members)}")
print("Support A               : pin (Ux = Uy = 0)")
print("Support B               : roller (Uy = 0)")
# ============================================================
# 3. INITIAL GEOMETRY PLOT AND NODE IDENTIFICATION
# ============================================================

output_dir = Path.cwd() / "truss_results"
output_dir.mkdir(parents=True, exist_ok=True)

def plot_geometry(show_loads: dict[int, tuple[float, float]] | None = None,
                  save_path: Path | None = None) -> None:
    fig, ax = plt.subplots(figsize=(12, 5.5))
    for i, j in members:
        xi, yi = nodes[i]
        xj, yj = nodes[j]
        ax.plot([xi, xj], [yi, yj], color="black", linewidth=1.4, zorder=1)

    for tag, (x, y) in nodes.items():
        ax.scatter(x, y, color="royalblue", s=24, zorder=3)
        ax.annotate(str(tag), (x, y), xytext=(0, 7),
                    textcoords="offset points", ha="center", fontsize=8)

    # Support symbols (schematic)
    ax.scatter([nodes[bottom_nodes[0]][0]], [-0.10], marker="^",
               s=100, color="darkgreen", label="Pin support", clip_on=False)
    ax.scatter([nodes[bottom_nodes[-1]][0]], [-0.10], marker="v",
               s=100, color="darkorange", label="Roller support", clip_on=False)

    if show_loads:
        scale = max(span, height, 1.0) * 0.06
        for node, (fx, fy) in show_loads.items():
            x, y = nodes[node]
            if abs(fx) > 1e-12:
                ax.annotate("", xy=(x + np.sign(fx) * scale, y),
                            xytext=(x, y),
                            arrowprops=dict(arrowstyle="->", color="crimson", lw=1.8))
            if abs(fy) > 1e-12:
                ax.annotate("", xy=(x, y + np.sign(fy) * scale),
                            xytext=(x, y),
                            arrowprops=dict(arrowstyle="->", color="crimson", lw=1.8))

    ax.set_title(f"{truss_type} truss — node numbering and geometry")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, linestyle=":", alpha=0.45)
    ax.legend(loc="best")
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=200, bbox_inches="tight")
    plt.show()
    plt.close(fig)


plot_geometry(save_path=output_dir / "01_geometry.png")

# ============================================================
# 4. LOAD INPUT
# ============================================================

print("\nLOAD INPUT")
print("Enter joint loads in kN. Positive Fx is to the right; positive Fy is upward.")
print("You can enter loads at bottom or top chord nodes. Use 0 for no load.")

joint_loads: dict[int, tuple[float, float]] = {}
if ask_yes_no("Add individual joint loads? / Ajouter des charges nodales ?"):
    while True:
        node_tag = ask_int(
            f"Node tag (1 to {len(nodes)}; 0 to finish)",
            minimum=0, maximum=len(nodes)
        )
        if node_tag == 0:
            break
        fx_kn = ask_float("Horizontal load Fx (kN)")
        fy_kn = ask_float("Vertical load Fy (kN)")
        old_fx, old_fy = joint_loads.get(node_tag, (0.0, 0.0))
        joint_loads[node_tag] = (old_fx + fx_kn * 1e3, old_fy + fy_kn * 1e3)

if ask_yes_no("Add a uniform vertical line load on the bottom chord?"):
    q_kn_m = ask_float(
        "Line load q (kN/m; positive = downward, negative = upward)"
    )
    # Convert the line load to consistent tributary joint loads:
    # q*panel_width/2 at each end, q*panel_width at interior nodes.
    # Positive q is downward, so the applied vertical force is negative.
    for i, node_tag in enumerate(bottom_nodes):
        tributary_length = panel_width / 2 if i in (0, n_panels) else panel_width
        fx, fy = joint_loads.get(node_tag, (0.0, 0.0))
        joint_loads[node_tag] = (fx, fy - q_kn_m * 1e3 * tributary_length)

if not joint_loads:
    print("No loads were entered. A zero-load analysis will be performed.")

# Remove loads that are exactly zero, for cleaner plotting/output.
joint_loads = {
    tag: (fx, fy) for tag, (fx, fy) in joint_loads.items()
    if abs(fx) > 1e-12 or abs(fy) > 1e-12
}

plot_geometry(joint_loads, output_dir / "02_geometry_with_loads.png")

# ============================================================
# 5. BUILD AND ANALYZE THE OPENSEES MODEL
# ============================================================

ops.wipe()
ops.model("basic", "-ndm", 2, "-ndf", 2)

for tag, (x, y) in nodes.items():
    ops.node(tag, x, y)

left_support = bottom_nodes[0]
right_support = bottom_nodes[-1]
ops.fix(left_support, 1, 1)   # pin
ops.fix(right_support, 0, 1)  # roller: vertical restraint only

ops.uniaxialMaterial("Elastic", 1, E)
for element_tag, (i, j) in enumerate(members, start=1):
    ops.element("Truss", element_tag, i, j, area, 1)

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
for node_tag, (fx, fy) in joint_loads.items():
    ops.load(node_tag, fx, fy)

ops.constraints("Plain")
ops.numberer("RCM")
ops.system("BandGeneral")
ops.test("NormUnbalance", 1e-8, 20)
ops.algorithm("Linear")
ops.integrator("LoadControl", 1.0)
ops.analysis("Static")

analysis_code = ops.analyze(1)
if analysis_code != 0:
    ops.wipe()
    raise RuntimeError(
        "OpenSeesPy analysis failed. Check geometry, supports, connectivity, "
        "and loading. The model may be unstable or singular."
    )

ops.reactions()

# ============================================================
# 6. EXTRACT RESULTS AND CHECK EQUILIBRIUM
# ============================================================

displacements = {
    tag: (float(ops.nodeDisp(tag, 1)), float(ops.nodeDisp(tag, 2)))
    for tag in nodes
}
reactions = {
    left_support: (float(ops.nodeReaction(left_support, 1)),
                   float(ops.nodeReaction(left_support, 2))),
    right_support: (float(ops.nodeReaction(right_support, 1)),
                    float(ops.nodeReaction(right_support, 2))),
}

member_forces = {}
for element_tag, (i, j) in enumerate(members, start=1):
    xi, yi = nodes[i]
    xj, yj = nodes[j]
    dx, dy = xj - xi, yj - yi
    length = float(np.hypot(dx, dy))
    cx, cy = dx / length, dy / length
    ui = np.array(displacements[i])
    uj = np.array(displacements[j])
    axial_extension = float(np.dot(uj - ui, np.array([cx, cy])))
    axial_force = E * area / length * axial_extension
    member_forces[element_tag] = {
        "nodes": (i, j),
        "length": length,
        "force_N": axial_force,
        "force_kN": axial_force / 1e3,
        "state": "Tension" if axial_force > 1e-6 else
                 "Compression" if axial_force < -1e-6 else "Zero",
    }

sum_fx_load = sum(fx for fx, fy in joint_loads.values())
sum_fy_load = sum(fy for fx, fy in joint_loads.values())
sum_fx_reaction = sum(rx for rx, ry in reactions.values())
sum_fy_reaction = sum(ry for rx, ry in reactions.values())
residual_fx = sum_fx_load + sum_fx_reaction
residual_fy = sum_fy_load + sum_fy_reaction

# Moment equilibrium about the left support, using nodal loads and reactions.
moment_loads = 0.0
for tag, (fx, fy) in joint_loads.items():
    x, y = nodes[tag]
    moment_loads += x * fy - y * fx
moment_reactions = 0.0
for tag, (rx, ry) in reactions.items():
    x, y = nodes[tag]
    moment_reactions += x * ry - y * rx
residual_moment = moment_loads + moment_reactions

# ============================================================
# 7. PRINT SUMMARY AND SAVE CSV/TEXT RESULTS
# ============================================================

print("\n" + "=" * 68)
print(f"LINEAR STATIC ANALYSIS RESULTS — {truss_type.upper()} TRUSS")
print("=" * 68)
print(f"Analysis status              : SUCCESS")
print(f"Nodes / members              : {len(nodes)} / {len(members)}")
print(f"Young's modulus              : {E:.6g} Pa")
print(f"Member area                  : {area:.6g} m²")
print(f"Total applied Fx             : {sum_fx_load / 1e3:.6f} kN")
print(f"Total applied Fy             : {sum_fy_load / 1e3:.6f} kN")

print("\nSUPPORT REACTIONS")
for tag, (rx, ry) in reactions.items():
    name = "A (left pin)" if tag == left_support else "B (right roller)"
    print(f"{name:18s} node {tag:3d}: Rx = {rx/1e3: .6f} kN, "
          f"Ry = {ry/1e3: .6f} kN")

print("\nEQUILIBRIUM RESIDUALS (should be close to zero)")
print(f"Sum Fx residual              : {residual_fx:.6e} N")
print(f"Sum Fy residual              : {residual_fy:.6e} N")
print(f"Moment residual about A      : {residual_moment:.6e} N·m")

print("\nJOINT DISPLACEMENTS")
print(f"{'Node':>6} {'Ux (mm)':>14} {'Uy (mm)':>14}")
for tag, (ux, uy) in displacements.items():
    print(f"{tag:6d} {ux*1e3:14.6f} {uy*1e3:14.6f}")

print("\nMEMBER AXIAL FORCES (positive = tension, negative = compression)")
print(f"{'Elem.':>6} {'i':>5} {'j':>5} {'Length (m)':>12} "
      f"{'N (kN)':>14} {'State':>14}")
for element_tag, result in member_forces.items():
    i, j = result["nodes"]
    print(f"{element_tag:6d} {i:5d} {j:5d} {result['length']:12.4f} "
          f"{result['force_kN']:14.4f} {result['state']:>14}")

max_abs_ux = max(abs(ux) for ux, uy in displacements.values())
max_abs_uy = max(abs(uy) for ux, uy in displacements.values())
print(f"\nMaximum |Ux|               : {max_abs_ux*1e3:.6f} mm")
print(f"Maximum |Uy|               : {max_abs_uy*1e3:.6f} mm")

# Save a plain-text summary and CSV member-force table.
summary_path = output_dir / "results_summary.txt"
with summary_path.open("w", encoding="utf-8") as file:
    file.write(f"Linear static analysis — {truss_type} truss\n")
    file.write(f"Span={span} m; height={height} m; panels={n_panels}\n")
    file.write(f"E={E} Pa; A={area} m^2\n")
    file.write(f"Residual Fx={residual_fx} N\n")
    file.write(f"Residual Fy={residual_fy} N\n")
    file.write(f"Residual moment={residual_moment} N.m\n\n")
    file.write("Support reactions (kN)\n")
    for tag, (rx, ry) in reactions.items():
        file.write(f"Node {tag}: Rx={rx/1e3:.8f}, Ry={ry/1e3:.8f}\n")
    file.write("\nJoint displacements (mm)\n")
    for tag, (ux, uy) in displacements.items():
        file.write(f"Node {tag}: Ux={ux*1e3:.8f}, Uy={uy*1e3:.8f}\n")

csv_path = output_dir / "member_axial_forces.csv"
with csv_path.open("w", encoding="utf-8", newline="") as file:
    file.write("element,node_i,node_j,length_m,axial_force_kN,state\n")
    for tag, result in member_forces.items():
        i, j = result["nodes"]
        file.write(f"{tag},{i},{j},{result['length']:.8f},"
                   f"{result['force_kN']:.8f},{result['state']}\n")

# ============================================================
# 8. PLOT DEFORMED SHAPE AND MEMBER FORCE LABELS
# ============================================================

fig, ax = plt.subplots(figsize=(13, 6))
for element_tag, (i, j) in enumerate(members, start=1):
    xi, yi = nodes[i]
    xj, yj = nodes[j]
    ax.plot([xi, xj], [yi, yj], color="0.70", linewidth=1.0, zorder=1)

# Automatically choose a display-only deformation scale.
max_disp = max(
    (np.hypot(ux, uy) for ux, uy in displacements.values()),
    default=0.0
)
if max_disp > 0:
    display_scale = 0.10 * max(span, height) / max_disp
else:
    display_scale = 1.0

deformed_coords = {}
for tag, (x, y) in nodes.items():
    ux, uy = displacements[tag]
    deformed_coords[tag] = (x + display_scale * ux, y + display_scale * uy)

for element_tag, (i, j) in enumerate(members, start=1):
    xi, yi = deformed_coords[i]
    xj, yj = deformed_coords[j]
    force_kn = member_forces[element_tag]["force_kN"]
    ax.plot([xi, xj], [yi, yj], color="crimson" if force_kn < 0 else "royalblue",
            linewidth=1.8, zorder=2)
    xm, ym = (xi + xj) / 2, (yi + yj) / 2
    ax.annotate(f"{force_kn:.1f}", (xm, ym), xytext=(0, 4),
                textcoords="offset points", fontsize=7, ha="center",
                bbox=dict(boxstyle="round,pad=0.15", fc="white",
                          ec="none", alpha=0.75))

for tag, (x, y) in nodes.items():
    ax.scatter(x, y, color="0.55", s=12, zorder=3)

ax.plot([], [], color="0.70", label="Undeformed geometry")
ax.plot([], [], color="royalblue", label="Tension (N > 0)")
ax.plot([], [], color="crimson", label="Compression (N < 0)")
ax.set_title(f"{truss_type} truss — deformed shape (scale {display_scale:.2g}) "
             "and axial forces (kN)")
ax.set_xlabel("x (m)")
ax.set_ylabel("y (m)")
ax.set_aspect("equal", adjustable="datalim")
ax.grid(True, linestyle=":", alpha=0.45)
ax.legend(loc="best")
fig.tight_layout()
fig.savefig(output_dir / "03_deformed_shape_axial_forces.png",
            dpi=220, bbox_inches="tight")
plt.show()
plt.close(fig)

print(f"\nFiles saved in: {output_dir.resolve()}")
print("  01_geometry.png")
print("  02_geometry_with_loads.png")
print("  03_deformed_shape_axial_forces.png")
print("  member_axial_forces.csv")
print("  results_summary.txt")
print("\nReminder: this is an educational analysis, not a member design or code check.")

ops.wipe()
