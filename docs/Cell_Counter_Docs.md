# OFM Cell Counter Server Setup
## Contents


## Introduction

This will be a place I will attempt to provide documentation on the Cell Counter software. A lot can be found in the README, but I will try to add more in-depth info here with time. 

## Cell Counter Application

All of the cell counter analysis scripts live in the `/home/openflexure/Applications/Cell_Counter` directory. If you want to modify most of the parameters of analysis, it will be in scripts found here. 

The desktop shortcuts link to one of 2 scripts found here:

1. The **Cell Counter Server** shortcut runs: `Cell_Counter_Main.py `

2. The **Cell Counter Local** shortcut runs `Cell_Counter_Main_Local.py`

Depending on which method you use for segmentation, you will want to make edits to the appropriate file. Some files are shared between the 2 approaches, so edits here will affect both scripts. 

## Changing Amount of Cell Suspension Used

If you find yourself wanting to use a different mounting volume of cell suspension (perhaps you may want to use a hemocytometer instead of the 22mm coverslips I suggest) then you will want to make an edit to line 168 in the above scripts

```python
cell_concentration = (cell_number_FOV * 3249.10716683)/0.05
```

0.05 denotes the volume  of the cell suspension in litres, so just change accordingly (e.g. 0.01 for 10 microliters).

## Modifying Motor Steps

If you find you have significant overlap between your FOV captured, you may need to change the amount of steps the stage moves before taking an image. 

To find out which step size would be best, run the **OFM Connect** tool, and use the **Navigate** tab to move the stage left/right and up/down, and see the minimum number of steps required to cover the size of the eFOV of the camera (i.e. move to an entirely new region of the coverslip). 

Then in `Microscope_Control_Functions.py`, change all of the `pos['x']` integers to the steps required to move the stage in the x plane (i.e. 'left-right'), and change all of the `pos['y']` integers to the steps required to move the stage in the y plane (i.e. 'up-down'). 

For example, if I required 12000 steps to move to a new FOV in the X, I would change `pos['x'] += 8400` to `pos['x'] += 12000`

```python
def Image_Acquisition(progress_callback):
    microscope = ofm_client.find_first_microscope()
    ret = microscope.autofocus() ## autofocus micro
    img_1 = microscope.capture_image()
    img_1.save("/home/openflexure/Applications/Cell_Counter/captured_images/image_1.tiff", format="tiff")
    progress_callback(1)
    pos = microscope.position
    starting_pos = pos.copy() ## for checking if final position is same as starting one, if not something has gone wrong
    pos['x'] += 8400
    microscope.move(pos)
    assert microscope.position == pos
    img_2 = microscope.capture_image()
    img_2.save("/home/openflexure/Applications/Cell_Counter/captured_images/image_2.tiff", format="tiff")
    progress_callback(2)
    pos['y'] += 6400
    microscope.move(pos)
    assert microscope.position == pos
    img_3 = microscope.capture_image()
    img_3.save("/home/openflexure/Applications/Cell_Counter/captured_images/image_3.tiff", format="tiff")
    progress_callback(3)
    pos['x'] -= 8400
    microscope.move(pos)
    assert microscope.position == pos
    img_4 = microscope.capture_image()
    img_4.save("/home/openflexure/Applications/Cell_Counter/captured_images/image_4.tiff", format="tiff")
    progress_callback(4)
    pos['y'] -= 6400
    microscope.move(pos)
    assert microscope.position == starting_pos
    #img_5 = microscope.capture_image()
    #img_5.save("/home/openflexure/Applications/Cell_Counter/captured_images/image_5.tiff", format="tiff")
    progress_callback(5)
```