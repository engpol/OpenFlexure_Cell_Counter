# OpenFlexure Cell Counter

A simple automated cell counter built on the [OpenFlexure Microscope](https://openflexure.org/),
using deep-learning segmentation to count cells in suspension to assist in calculating
concentrations — all in under 30 seconds, without a haemocytometer.

> 📝 **TODO —** Add a photo or short GIF of the assembled instrument here. It is
> the single most useful thing on the page for a first-time reader.

> 📝 **TODO —** Add badges (licence, DOI, build status) once you've chosen a
> licence and, if you plan to, minted a Zenodo DOI.

---

## Contents

- [What this is](#what-this-is)
- [Who it's for](#who-its-for)
- [How it works](#how-it-works)
- [What you'll need](#what-youll-need)
- [Repository structure](#repository-structure)
- [Getting started](#getting-started)
- [Daily use](#daily-use)
- [How the concentration is calculated](#how-the-concentration-is-calculated)
- [Validating your instrument](#validating-your-instrument)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [Licence and citation](#licence-and-citation)

---

## What this is

Counting cells with a haemocytometer is slow, tedious, and notoriously variable
between operators. Automated cell counters solve this but cost several thousand
pounds and lock you into proprietary consumables.

This project turns an OpenFlexure Microscope — an open-source, 3D-printed,
motorised microscope — into an automated cell counter. You pipette your
suspension onto a coverslip, press a button, and get a cell count and
concentration back in a few seconds.

**What makes it different from just running a counting app:** cell segmentation
uses [Cellpose](https://www.cellpose.org/), a deep-learning model that handles
touching, overlapping, and irregularly shaped cells far better than the
threshold-and-watershed approach in most free tools. 

> 📝 **TODO —** Add a sentence on which cell type(s) you have validated this
> with, and the concentration range over which it works. Readers will want to
> know whether it applies to their cells.

---

## Who it's for

This Cell Counter, as the OpenFlexure Microscope itself, is designed to be assembled and be usable by someone with **no programming experience**. The setup involves a few one-time steps that can be walked through
click-by-click; after that, daily use is a graphical interface with a button
that says "Capture".

You will need to be comfortable with:

- Pipetting onto a coverslip
- Following a step-by-step setup guide once
- Asking your IT team a simple question (we've drafted the wording for you)

You will **not** need to write code, use a command line day-to-day, or
understand how the machine learning works.

---

## How it works

There are two computers involved, which sounds more complicated than it is.

```
   YOU                MICROSCOPE                    ANALYSIS COMPUTER
    │                (Raspberry Pi)                  (any Windows/Linux PC)
    │                      │                                │
    │  pipette sample      │                                │
    │─────────────────────►│                                │
    │  press "Capture"     │                                │
    │─────────────────────►│                                │
    │                      │  moves stage, takes            │
    │                      │  4 photos, joins them          │
    │                      │                                │
    │                      │───── sends image ─────────────►│
    │                      │                                │  finds every cell
    │                      │                                │  using Cellpose
    │                      │◄──── count + outlines ─────────│
    │                      │                                │
    │  count, concentration│                                │
    │  and a picture of    │                                │
    │◄─────────────────────│                                │
    │  what was counted    │                                │
```

**Why two computers?** The Raspberry Pi inside the microscope is excellent at
controlling motors and cameras, but too slow to run a modern segmentation model
— it would take several minutes per sample. A normal desktop PC does the same
job in a few seconds. The two are connected by a single Ethernet cable.

**Why the model stays loaded.** The analysis computer runs a small program that
loads Cellpose once when it starts and then keeps it in memory. Loading the
model takes longer than using it, so keeping it warm is what makes each
measurement fast rather than slow.

---

## What you'll need

### Hardware

| Item | Notes | Approx. cost |
|---|---|---|
| [OpenFlexure Microscope](https://openflexure.org/) | Simple optics are sufficient and use most up-to-date hardware version | <!-- TODO --> |
| Raspberry Pi 4B | I used 4B, but 2 GB is sufficient | <!-- TODO --> |
| Analysis computer | Any PC running Windows 10 and above. If not using GitHub method | Existing hardware |
| Ethernet patch cable | Ordinary cable | ~£5 |
| 22 × 22 mm glass coverslips | Whatever's cheapest, I just wash and re-use mine until they crack | £5 |
| 3D-printed parts | STLs in [`hardware/`](hardware/) | Filament cost |

> 📝 **TODO —** Fill in costs and add anything specific to your build (slide
> holders, illumination changes, custom stage inserts). A total build cost is
> the number readers will look for first.

### Software

Everything needed is free and open-source. The setup guides install it for you.

- Raspberry Pi OS on the microscope (a pre-configured image is provided)
- Python plus Cellpose on the analysis computer

---

## Repository structure

```
.
├── hardware/              3D-printable parts and assembly notes
│   ├── stl/               Ready-to-print STL files
│   ├── source/            Editable CAD source
│   └── ASSEMBLY.md        Build instructions
│
├── microscope/            Software that runs on the Raspberry Pi
│   ├── Cell_Counter_Main.py          The graphical interface
│   ├── Microscope_Control_Functions.py   Stage movement and image capture
│   ├── Image_tiling.py               Joins the four images together
│   └── Server_Workflow.py            Talks to the analysis computer
│
├── server/                Software that runs on the analysis computer
│   ├── worker.py          Keeps Cellpose loaded and answers requests
│   ├── benchmark.py       Measures speed and calibrates cell diameter
│   ├── requirements.txt   Python packages needed
│   └── run_worker.bat     Starts the analysis service on Windows
│
├── docs/                  Setup guides
│   ├── SETUP.md           Full installation walkthrough
│   ├── DIRECT_LINK_ADMIN.md   Connecting the two computers
│   └── NETWORK_SETUP.md   Alternatives for different lab networks
│
└── examples/              Sample images and expected outputs
```

> 📝 **TODO —** Adjust to match your actual layout, and add a link to the
> pre-configured Raspberry Pi image (it will be too large for GitHub — Zenodo or
> institutional storage works well, and Zenodo gives you a DOI).

---

## Getting started

Budget about **two hours** for first-time setup, most of which is unattended
installation.

### 1. Build the microscope

Follow the [OpenFlexure assembly instructions](https://build.openflexure.org/),
then add the parts from [`hardware/`](hardware/). See
[`hardware/ASSEMBLY.md`](hardware/ASSEMBLY.md).

### 2. Flash the Raspberry Pi

Download the pre-configured image (link above) and write it to an SD card with
[Raspberry Pi Imager](https://www.raspberrypi.com/software/). Everything —
microscope software, network settings, cell counter — is already installed.

> 📝 **TODO —** State the default username and password, and tell users to
> change them. Also note the image size and SD card requirement.

### 3. Connect the two computers

Plug an Ethernet cable between the microscope and the analysis computer, then
follow [`docs/DIRECT_LINK_ADMIN.md`](docs/DIRECT_LINK_ADMIN.md). It's a
click-by-click guide that assumes no networking knowledge.

If your lab already has a normal wired network, the two machines may be able to
talk to each other with no configuration at all — see
[`docs/NETWORK_SETUP.md`](docs/NETWORK_SETUP.md) for how to check.

> **A note for institutional users.** University networks (eduroam and similar)
> usually stop devices talking to each other for security reasons. This is why
> we recommend a direct cable: it sidesteps the issue entirely and doesn't
> depend on your IT department's configuration. If your analysis computer is
> managed by IT, do check with them before connecting a second network cable —
> `docs/DIRECT_LINK_ADMIN.md` includes a short message you can send.

### 4. Install the analysis software

Follow [`docs/SETUP.md`](docs/SETUP.md) Part A. It installs Python and Cellpose
into a self-contained folder, so nothing else on the computer is affected.

### 5. Calibrate

**Don't skip this.** Run the calibration described in
[Validating your instrument](#validating-your-instrument) before using the
counter for real experiments.

---

## Daily use

1. Turn on the microscope and the analysis computer. The analysis service starts
   by itself.
2. Pipette **50 µL** of cell suspension onto a 22 × 22 mm coverslip and mount it.
3. Launch the cell counter:
   ```bash
   ./Cell_Counter_Activate.sh
   ```
   > 📝 **TODO —** If you've added a desktop shortcut to the image, describe it
   > here instead — most users would rather double-click an icon.
4. Focus using the on-screen controls.
5. Press **Capture**. The microscope takes four images across the coverslip.
6. Press **Process**. Results appear in a few seconds:
   - Total cells counted
   - Concentration in cells/mL
   - An image showing exactly which cells were counted

**Always look at the outline image.** It's the quickest way to spot a bad count —
debris counted as cells, clumps counted as one, or cells missed because the
focus drifted.

> 📝 **TODO —** Add a screenshot of the interface with results shown.

---

## How the concentration is calculated

Worth understanding, because it's where most errors come from.

The microscope photographs **four fields of view**, which together cover a small
fraction of the coverslip:

| Quantity | Value |
|---|---|
| Area of one field of view | 0.0584 mm² |
| Four fields combined | 0.2336 mm² |
| Area of a 22 × 22 mm coverslip | 484 mm² |
| **Fraction of the sample you actually see** | **1 / 2072** |

So if the microscope counts 150 cells:

```
Total cells on coverslip  = 150 × 2072  = 310,800 cells
Volume pipetted           = 50 µL       = 0.05 mL
Concentration             = 310,800 / 0.05 = 6.2 × 10⁶ cells/mL
```

This assumes the cells are **evenly distributed** across the coverslip. Let the
sample settle, mix it thoroughly before pipetting, and take a second reading if a
number looks surprising.

> 📝 **TODO —** If you use a different coverslip size or volume, update the
> constants in `Cell_Counter_Main.py` and this table together — they must match.

---

## Validating your instrument

Every build is slightly different. Two checks before you trust the numbers.

### 1. Set the expected cell diameter

Cellpose needs to know roughly how large your cells are, in pixels. Getting this
wrong affects both accuracy and speed.

On the analysis computer:

```bash
python benchmark.py path/to/an/image.tiff
```

This estimates the diameter from your own images and reports how long
segmentation takes at different settings. Put the recommended value in
`~/.cell_counter/server.conf` on the microscope:

```
diameter = 40
```

> 📝 **TODO —** Record the value that works for your cell line here, so users
> starting with the same cells have a sensible default.

### 2. Compare against a haemocytometer

Run the same suspension both ways, across at least three different
concentrations spanning your working range. They should agree within the
haemocytometer's own variability (typically ±10–20%).

If they disagree systematically:

| Pattern | Likely cause |
|---|---|
| Counter always reads **high** | Debris counted as cells, or the four fields overlap so some cells are counted twice |
| Counter always reads **low** | Cells out of focus, diameter set too small, or cells too sparse |
| Disagreement grows with concentration | Cells clumping, or overlapping cells merged into one object |

> 📝 **TODO —** Add your own validation data — a scatter plot of this counter
> against haemocytometer counts is the single most persuasive figure you can put
> in this README, and reviewers will ask for it.

---

## Limitations

Being upfront about these:

- **Not a validated clinical or diagnostic device.** This is a research tool.
- **Cells must be reasonably well separated.** Dense or heavily clumped
  suspensions will undercount, as clumps get merged.
- **No viability staining.** This counts cells, it does not distinguish live from
  dead. Trypan blue exclusion is not currently supported.
  > 📝 **TODO —** Remove or amend if you have added this.
- **Assumes even settling.** Uneven distribution across the coverslip is the
  largest single source of error.
- **Field-of-view geometry is build-specific.** The area constants assume a
  particular optics module and camera; if you change either, recalibrate.
- **The four fields may overlap slightly.** Stage movement is calibrated in
  motor steps rather than measured distance, so a small overlap can cause modest
  double-counting. Worth checking with a stage graticule if you need high
  accuracy.

---

## Troubleshooting

| Problem | What to check |
|---|---|
| "Could not reach the analysis server" | Is the analysis computer on and the service running? Is the Ethernet cable plugged in at both ends? |
| "Server rejected the auth token" | The security code on the microscope and the analysis computer don't match — see `docs/SETUP.md` step A3 |
| Count is obviously wrong | Look at the outline image. Usually focus, or the diameter setting |
| Everything counted as one big blob | Diameter set far too large |
| Nothing detected at all | Diameter set far too small, or the image is out of focus |
| Analysis takes minutes, not seconds | The service restarted and is reloading the model — the first run after startup is always slower |

More detail in [`docs/SETUP.md`](docs/SETUP.md) and
[`docs/DIRECT_LINK_ADMIN.md`](docs/DIRECT_LINK_ADMIN.md).

Still stuck? [Open an issue](../../issues) with the error message, what you were
doing, and a photo of the result image if relevant.

---

## Contributing

Contributions are very welcome, especially:

- Validation data from other cell types or labs
- Improvements to the 3D-printed parts
- Support for viability staining
- Testing on Linux or macOS analysis computers

Please open an issue before starting substantial work, so we can avoid
duplication.

> 📝 **TODO —** Add a CONTRIBUTING.md and a code of conduct if you expect
> outside contributors.

---

## Licence and citation

> 📝 **TODO —** Choose a licence. Note that if your hardware derives from
> OpenFlexure parts you may be constrained by their licence terms (CERN-OHL for
> hardware, and check the software licence separately). Common choices:
> CERN-OHL-S for hardware, MIT or GPL-3.0 for software.

If you use this in published work, please cite the underlying tools:

**OpenFlexure Microscope**
Collins, J.T. et al. Robotic microscopy for everyone: the OpenFlexure
microscope. *Biomedical Optics Express* **11**, 2447–2460 (2020).

**Cellpose**
Stringer, C., Wang, T., Michaelos, M. & Pachitariu, M. Cellpose: a generalist
algorithm for cellular segmentation. *Nature Methods* **18**, 100–106 (2021).

Pachitariu, M. & Stringer, C. Cellpose 2.0: how to train your own model.
*Nature Methods* **19**, 1634–1641 (2022).

> 📝 **TODO —** Verify these citations against the publisher records, and add
> your own paper or preprint once available.

---

## Acknowledgements

> 📝 **TODO —** Funders, supervisors, lab members, and the OpenFlexure and
> Cellpose developer communities.
