# OpenFlexure Cell Counter

A simple automated cell counter built on the [OpenFlexure Microscope](https://openflexure.org/),
using either traditional contrast-based or deep-learning segmentation to count cells in suspension to assist in calculating
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
pounds, lock you into proprietary consumables, and are impossible to repair yourself.

This project turns an OpenFlexure Microscope — an open-source, 3D-printed,
motorised microscope — into an automated cell counter. You pipette your
suspension onto a coverslip, press a button, and get a cell count and
concentration back in a few seconds. 

As a side-note, the microscope is a fully motorized and customisable brightfield microscope; the software provided here is simply a single use-case.

There are 2 options for performing cell segmentation; either a traditional threshold-and-watershed approach or one that uses [Cellpose](https://www.cellpose.org/), a deep-learning model that handles
touching, overlapping, and irregularly shaped cells far better.

The Cellpose model included in the RPi image is **cyto2** fine tuned on images of HEK-293 cells taken on several different OpenFlexure microscopes. It is very easy to swap out the model used for one that you have trained yourself, as is covered in the server setup guide. 


> 📝 **TODO —** Add a sentence on which cell type(s) you have validated this
> with, and the concentration range over which it works. Readers will want to
> know whether it applies to their cells.

---

## Who it's for

This Cell Counter, as the OpenFlexure Microscope itself, is designed to be assembled and be usable by someone with **no programming or engineering experience**. The setup involves a few one-time steps for which detailed click-by-click guides have been written out; after that, daily use is a graphical interface with a few buttons.

You will need to be comfortable with:

- Pipetting onto a coverslip
- Following a step-by-step setup guide once


You will **not** need to write code, use a command line day-to-day, or
understand how the machine learning works. However, information on all of the code is provided if you would wish to adapt/improve on what I have made here. 

---

## How it works

The process of counting cells is functionally identical to what can be done manually in a haemocytometer. However we can use the fact that the exact effective field of view of the camera is known, to forgo the need for a machined chamber.  

The microscope photographs **four fields of view**, which together cover a small
fraction of the coverslip:

| Quantity | Value |
|---|---|
| Area of one field of view | 0.0584 mm² |
| Four fields combined | 0.2336 mm² |
| Area of a 22 × 22 mm coverslip | 484 mm² |
| **Fraction of the sample you actually see** | **1 / 2072** |

Then the microscope will use one of either methods to calculate the number of cells across all 4 images.

So if the microscope counts 150 cells:

```
Total cells on coverslip  = 150 × 2072  = 310,800 cells
Volume pipetted           = 50 µL       = 0.05 mL
Concentration             = 310,800 / 0.05 = 6.2 × 10⁶ cells/mL
```

This calculation only works on assumption the cells are **evenly distributed** across the coverslip. Thus it is important to let the
sample settle, mix it thoroughly before pipetting, and take a second reading if a
number looks surprising.


---

## What you'll need

### Hardware

| Item | Notes | Approx. cost |
|---|---|---|
| [OpenFlexure Microscope](https://openflexure.org/) | Simple optics are sufficient and use most up-to-date hardware version | ~100£ or ~160£ from a vendor (Exluding RPi) |
| Raspberry Pi 4B | I used 4B, but 2 GB is sufficient | These have recently got more expensive, so expect 50-90£ |
| Analysis computer (Optional) | Any old PC that can be connected to the scope via an ethernet cable. Helps tremendously if it has an NVIDIA Graphics card supporting CUDA, but is not an absolute requirement. | Existing hardware |
| Ethernet patch cable (Optional) | Ordinary cable | ~£5 |
| 22 × 22 mm glass coverslips | Whatever's cheapest, I just wash and re-use mine until they crack | £5 |
| 3D-printed parts | STLs in [`hardware/`](hardware/) | Filament cost or ~10£ if using external service |

### Total Cost:

**~ 200£** (Excluding Analysis PC - the cost of this will vary depending on what you have lying around) 

### Software

Everything needed is free and open-source. The easiest way to get the cell counter running is by using the pre-configured image which can be downloaded using the button below (~9.1 GB).

[![Download](https://img.shields.io/badge/Download-OFM_Cell_Counter_IMAGE_(9.1_GB)-blue?style=for-the-badge&logo=download)](https://archive.org/download/ofm-cell-counter/OFM_Cell_Counter.img)


---

## Getting started

Budget about **two hours** for first-time setup, excluding building the microscope.

### 1. Build the microscope

Acquire all parts required for the "Basic Optics" variant of the Open Flexure Microscope, and follow the [OpenFlexure assembly instructions](https://build.openflexure.org/). Please check out the list of [associated vendors](https://openflexure.org/about/vendors) if you would prefer to simply buy a complete assembly kit for the microscope.
Then, once you have finished the build, add the parts from [`STLs`](STLS/Custom_Holder). See
[`ASSEMBLY.md`](ASSEMBLY.md).

### 2. Flash the Raspberry Pi

Download the pre-configured image (link above) and write it to an SD card with
[Raspberry Pi Imager](https://www.raspberrypi.com/software/). Everything —
OpenFlexure microscope software, network settings, Cell Counter — is already installed.

I recommend a 32 GB SSD, but anything above 10 GB should be fine.

The thresholding-watershed method for Cell Segmentation can run directly from the RPi so, if you do not wish to run Cellpose, this is all you would need to have a functional Cell Counter!

### 3. OPTIONAL - IF USING CELLPOSE

If wanting to use Cellpose for segmentation, you will need a second computer to run the Cellpose segmentation. 

Sadly, some of the Cellpose dependencies (Torch) are very hard to setup and run dreadfully slow on the 32-bit ARM OS that is required by the OFM. Even after getting it working in my trials, running CellPose on even a couple images on the OFM itself took ~ 15 mins, making it non-viable for daily use.

If you have any old PC lying around, this can be turned into a "server" which can process images taken on the OFM Cell Counter. The process outlining how to do this can be found in [docs/SERVER_SETUP](docs/SERVER_SETUP.md).

The server setup assumes that you may not have full admin rights/control over your WiFI network (As is the case for me, using institutional WiFi). This is why, at least in my guide, the server will have to be directly connected to the Cell Counter via an ethernet cable. Keep this in mind if you are short on space/were hoping to have the server placed in a different room to the cell counter.


### 4. Calibrate

**Don't skip this.** Run the calibration described in
[Validating your instrument](#validating-your-instrument) before using the
counter for real experiments.

---

## Daily use 

1. Turn on the microscope (and optionally the analysis computer). The analysis service starts
   by itself.
2. Pipette **50 µL** of cell suspension onto a 22 × 22 mm coverslip and mount it.
3. Launch the appropriate Cell Counter using the Desktop Shortcut:
    - **Cell Counter Server (fast)** = Use Cellpose (requires ethernet connection to analysis computer)
    - **Cell Counter Local (very fast)** = Use Contrast-based Thresholding (runs on RPi itself) 
4. Press **Ok**. The microscope takes four images across the coverslip.
6. Results appear in a few seconds:
   - Total cells counted
   - Concentration in cells/mL
   - An image showing exactly which cells were counted
Use the on-screen calculator to perform desired dilution calculations

**Always look at the outline image.** It's the quickest way to spot a bad count —
debris counted as cells, clumps counted as one, or cells missed because the
focus drifted. If there are any problems, try to ammend them, and count again. 

If the focus has drifted far too much, you may need to re-focus using the **OFM Connect** tool, which gives you full control over the microscope.



---


## Validating your instrument

Every build is slightly different. Two checks before you trust the numbers.

### 1. CELLPOSE 

Cellpose needs to know roughly how large your cells are, in pixels. Getting this wrong affects both accuracy and speed. If you are finding that you are getting poor segmentation on your cells, before deciding to train your own model, it is worth checking that changing the diameter parameter won't fix your issues. 

As outlined above, this Cell Counter was validated and setup for HEK-293 cells (where I found a diam value of 15.328 worked best). However, if your cells are significantly smaller/larger, you may need to adjust this parameter.

To find a good value for this, take a couple images of your cells on your OFM and send it to a PC capable of running cellpose. You will essentially be wanting to open the [Cellpose GUI](https://cellpose.readthedocs.io/en/latest/gui.html), import this image, and press the 'Calibrate' button to find a recommended diameter value. You can also follow this [YouTube guide](https://www.youtube.com/watch?v=5qANHWoubZU) to see how to do this in more detail (From start until ~7 mins in).

Once you have the recommended diameter value, change it in the
`~/.cell_counter/server.conf` file on the microscope:

```
diameter = 40
```

### 2. Compare against a haemocytometer

Run the same suspension both ways, across at least three different
concentrations spanning your working range. They should agree within the
haemocytometer's own variability (typically ±10–20%).

If they disagree systematically:

| Pattern | Likely cause |
|---|---|
| Counter always reads **high** | Debris counted as cells, the four fields overlap so some cells are counted twice |
| Counter always reads **low** | Cells out of focus, diameter set too small, or cells too sparse |
| Disagreement grows with concentration | Cells clumping, or overlapping cells merged into one object |



---

## Limitations

Being upfront about these:

- **Not a validated clinical or diagnostic device.** This is a research tool.
- **Cells must be reasonably well separated.** Dense or heavily clumped
  suspensions could undercount, as clumps get merged.
- **No viability staining.** This counts cells, it does not distinguish live from
  dead. Trypan blue exclusion is not currently supported.
- **Assumes even settling.** Uneven distribution across the coverslip is the
  largest single source of error.
- **Field-of-view geometry is build-specific.** The area constants assume the a specific optics module and camera used in the 'Basic Optics' configuration of the OFM; if you change either, you would have to re-calibrate and modify some of the code.
- **The four fields may overlap slightly.** Stage movement is calibrated in
  motor steps rather than measured distance, so a small overlap can cause modest
  double-counting. Double check in the output no overlap is present.

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


---

## Licence and citation


If you use this in published work, please cite the underlying tools:

**OpenFlexure Microscope**
Collins, J.T. et al. Robotic microscopy for everyone: the OpenFlexure
microscope. *Biomedical Optics Express* **11**, 2447–2460 (2020).

**Cellpose**
Stringer, C., Wang, T., Michaelos, M. & Pachitariu, M. Cellpose: a generalist
algorithm for cellular segmentation. *Nature Methods* **18**, 100–106 (2021).

Pachitariu, M. & Stringer, C. Cellpose 2.0: how to train your own model.
*Nature Methods* **19**, 1634–1641 (2022).

---

## Acknowledgements

