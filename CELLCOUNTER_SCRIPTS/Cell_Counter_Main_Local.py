import sys
from PIL import Image
import threading
import time
import io
import os
import FreeSimpleGUI as sg
import Microscope_Control_Functions as scope
import Local_Workflow as online_process
import Image_tiling as image_tile


layout = [[sg.Text('Please press Ok after pippeting 50 uL of cells'), sg.B('Ok')],[sg.ProgressBar(max_value=5, orientation='h', size = (40,20), key='-PROGRESS-')],[sg.T('No Images Taken', key='-TEXT-')]] #define window layout
window = sg.Window('Cell Counter', layout) # save window layout into object with title

while True:
    event, values = window.read() ## show window
    if event == sg.WIN_CLOSED:
        sys.exit() # terminate script
    elif event == 'Ok': # Normally name of button corresponds to its event name, if no key is given
        window['-TEXT-'].update('Focusing microscope...')
        window.refresh()# Force window to update
        def update_progress_bar(current):
            window['-PROGRESS-'].update(current)
            window['-TEXT-'].update(f'{current} images taken')
            window.refresh()
        scope.Image_Acquisition(update_progress_bar) ## Auto focus and acquire 4 images in a 4x4 grid and return to center
        break
window.close()

def convert_tiff_to_png(tiff_path,max_size): ## convert images into .PNG and reduce in size to fit screen 
    with Image.open(tiff_path) as img:
        img = img.convert("RGBA")  # Ensure compatibility
        img.thumbnail(max_size) ## reduce image size to that N x N pixel grid specified
        bio = io.BytesIO() ## Create an in-memory byte stream - required for displaying in FreeSimpleGUI
        img.save(bio, format="PNG") ## convert to PNG which is compatible with sg
        return bio.getvalue()
    
image_dir = "/home/openflexure/Applications/Cell_Counter/captured_images" ## Define dir where images from scope are saved

image_tile.tile_4_tiff(image_dir)

max_size = (300,300)

chosen_image = convert_tiff_to_png("/home/openflexure/Applications/Cell_Counter/chosen_image/chosen_image.tiff",max_size)

'''##COMMENT OUT
tiff_files = [os.path.join(image_dir,file) for file in os.listdir(image_dir) if file.lower().endswith('.tiff')]  ## save all .tiff images from dir into a list

max_size = (300,300) ## Max image size for convert_tiff... defined above
images = [convert_tiff_to_png(file, max_size) for file in tiff_files] ## list containing scope images resized and converted to png

layout = [
    [sg.T('PLEASE CLICK THE IMAGE CONTAINING THE GREATEST SPREAD OF CELLS TO COUNT')],
    [sg.B(image_data=images[0], k='-IMG0-', enable_events= True), sg.B(image_data=images[1],k='-IMG1-', enable_events= True)], ##K = KEY enable events allows for button click to be recorded
    [sg.B(image_data=images[2],k='-IMG2-', enable_events= True), sg.B(image_data=images[3],k='-IMG3-', enable_events= True)]
]

window = sg.Window("SELECT IMAGE TO SEGMENT", layout)

print(f"{tiff_files[0]}")

while True:
    event, values = window.read()
    if event == sg.WIN_CLOSED:
        break
    if event == '-IMG0-':
        chosen_image = images[0]
        chosen_image_save = Image.open(tiff_files[0])
        chosen_image_save.save("/home/openflexure/Applications/Cell_Counter/chosen_image/chosen_image.tiff", format="TIFF")
        break
    if event == '-IMG1-':
        chosen_image = images[1]
        chosen_image_save = Image.open(tiff_files[1])
        chosen_image_save.save("/home/openflexure/Applications/Cell_Counter/chosen_image/chosen_image.tiff", format="TIFF")
        break
    if event == '-IMG2-':
        chosen_image = images[2]
        chosen_image_save = Image.open(tiff_files[2])
        chosen_image_save.save("/home/openflexure/Applications/Cell_Counter/chosen_image/chosen_image.tiff", format="TIFF")
        break
    if event == '-IMG3-':
        chosen_image = images[3]
        chosen_image_save = Image.open(tiff_files[3])
        chosen_image_save.save("/home/openflexure/Applications/Cell_Counter/chosen_image/chosen_image.tiff", format="TIFF")
        break
window.close()
'''###COMMENT OUT


layout = [[sg.Image(data=chosen_image),sg.T('PLEASE WAIT FOR CELLS TO BE SEGMENTED'), sg.Image(data=sg.DEFAULT_BASE64_LOADING_GIF, enable_events=True, key='-GIF-IMAGE-')]]

window = sg.Window("PLEASE WAIT", layout)

def process_images_thread(window):
    """Runs the image processing in a separate thread."""
    def status(msg):
        window.write_event_value('-STATUS-',msg)
    # Simulate a long-running process
    online_process.Process_Images(status_callback=status)  # Replace with your actual processing function
    # Send a message back to the main thread when done
    window.write_event_value('-PROCESS-DONE-', 'Done')  # Notify the GUI

# Start the processing thread
thread = threading.Thread(target=process_images_thread, args=(window,), daemon=True)
thread.start()

while True:
    event, values = window.read(timeout=100)  # Necessary for GIF updates
    if event == sg.WIN_CLOSED:
        break
    # Update the GIF animation
    window['-GIF-IMAGE-'].update_animation(sg.DEFAULT_BASE64_LOADING_GIF, time_between_frames=100)
    # Check if the thread finished processing
    if event == '-PROCESS-DONE-':
        print("Processing complete:", values[event])  # Handle completion
        break
window.close()


''' ### COMMENT OUT 
def convert_tiff_to_png(tiff_path,max_size): ## convert images into .PNG and reduce in size to fit screen 
    with Image.open(tiff_path) as img:
        img = img.convert("RGBA")  # Ensure compatibility
        img.thumbnail(max_size) ## reduce image size to that N x N pixel grid specified
        bio = io.BytesIO() ## Create an in-memory byte stream - required for displaying in FreeSimpleGUI
        img.save(bio, format="PNG") ## convert to PNG which is compatible with sg
        return bio.getvalue()
max_size = (300,300)
chosen_image = convert_tiff_to_png("/home/openflexure/Applications/Cell_Counter/chosen_image/chosen_image.tiff",max_size)
''' ## COMMENT OUT


def PNG_to_GUI(tiff_path, max_size): ## convert images into .PNG and reduce in size to fit screen 
    with Image.open(tiff_path) as img:
        img.thumbnail(max_size, resample=Image.Resampling.LANCZOS) ## reduce image size to that N x N pixel grid specified
        bio = io.BytesIO() ## Create an in-memory byte stream - required for displaying in FreeSimpleGUI
        img.save(bio, format="PNG") ## convert to PNG which is compatible with sg
        return bio.getvalue()
    
mask_image = PNG_to_GUI('/home/openflexure/Applications/Cell_Counter/workflow_files/image_mask.png', max_size)

ffcorr_image = convert_tiff_to_png("/home/openflexure/Applications/Cell_Counter/workflow_files/chosen_image_corrected.tiff", max_size)

cell_number_path = "/home/openflexure/Applications/Cell_Counter/workflow_files/cell_number.txt"

with open(cell_number_path, "r") as file:
    number = file.read().strip()  # Read the content and remove any leading/trailing whitespace
    try:
        cell_number_FOV = float(number)  # Convert the string to a float
        print(f"The cell number is: {cell_number_FOV}")
    except ValueError:
        print("The file does not contain a valid float.")
        
### From OF forums = pixel size of OFM using PiCamera v2 and basic camera optics = 85 nM.  
### For native resolution of (2464x3280), the calculated FOV for 1 image is 0.058391872 mm2 (0.233567488 mm2 for 4 tiled images)
### If cells are equally distributed across the 22mmx22mm coveslip (484 mm2), the tiled area represents 0.00048257745 % of total area 
### Multiply by 2072.20623342 to get total cells, then divide by decided volume (50 uL) to get cells / ml etc.
        

### Calculated Mag = fl of Tube Lens / Cam Lens (3.04mm) = 50/3.04 = 16.45 effective magnification
### Sensor size = 3.68 mm x 2.76 mm. 3.68/16.45 = 0.223 mm, 2.76/16.45 = 0.167 mm
##  If size is 0.223 mm x 0.167 mm, the calculated FOV for 1 image is 0.037241 mm2, (0.148963 mm2 for 4 tiled images)
## 0.148963/484 = 0.00030777685 % of total area
## Multiply by 3249.10716683 to get total cells then divide by 50
        
## I will go with the below calc for now, as I cannot really find out how the above was calculated, although it may be more accurate.

cell_concentration = (cell_number_FOV * 3249.10716683)/0.05

PREDEFINED_STOCK_CONC = cell_concentration

def calculate_dilution(final_conc, stock_conc, final_vol, cell_unit, stock_unit, final_unit):
    """
    Calculate the volume of stock solution needed for dilution.
    """
    # Convert units to same scale (factor of 1000)
    unit_conversion = {"L": 1, "mL": 1e-3, "µL": 1e-6}

    try:
        final_conc = float(final_conc)
        final_vol = float(final_vol)
        

        if stock_unit in unit_conversion and final_unit in unit_conversion:
            # Adjust the final volume to the same base unit as the stock concentration
            final_vol_in_liters = final_vol * unit_conversion[final_unit]
            
            # Adjust the final cell conc to the same base unit as the stock concentration
            final_conc_in_litres = final_conc / unit_conversion[cell_unit]
           
            # Calculate the required stock volume in liters
            stock_vol_in_liters = ((final_conc_in_litres * final_vol_in_liters) / (stock_conc*1000))

            # Convert the stock volume to the selected unit
            stock_vol_in_selected_unit = stock_vol_in_liters / unit_conversion[stock_unit]
            
            media_volume_in_selected_unit = (final_vol_in_liters / unit_conversion[stock_unit]) - stock_vol_in_selected_unit
            
            return f"Add {media_volume_in_selected_unit:.3f} {stock_unit} of culture media to {stock_vol_in_selected_unit:.3f} {stock_unit} of your cell suspension"
        else:
            return "Invalid unit selection."
    except (ValueError, ZeroDivisionError):
        return "Error: Please ensure all values are valid and stock concentration is not zero."

layout = [
    [sg.T('Masking Output!')],
    [sg.Image(data=ffcorr_image), sg.Image(mask_image)],
    [sg.Text("Original Cell Concentration:"), sg.Text(f"{PREDEFINED_STOCK_CONC:,.0f} cells / mL")],

    [sg.Text("Final Cell Concentration:"), sg.Input(key="-FINAL_CONC-", size=(10, 1)), sg.Text("cells / "),
     sg.Combo(["L", "mL", "µL"], default_value="mL", key="-CELL_UNIT-")],

    [sg.Text("Desired Final Volume:"), sg.Input(key="-FINAL_VOL-", size=(10, 1)), sg.Text("units:"),
     sg.Combo(["L", "mL", "µL"], default_value="mL", key="-FINAL_UNIT-")],
    
    [sg.T("Pipetting Units:"),sg.Combo(["L", "mL", "µL"], default_value="mL", key="-STOCK_UNIT-")],

    [sg.Button("Calculate"), sg.Button("Exit")],

    [sg.Text("", key="-RESULT-")]
]


# Create the window
window = sg.Window("Dilution Calculator", layout)

# Event loop
while True:
    event, values = window.read()

    if event == sg.WINDOW_CLOSED or event == "Exit":
        break

    if event == "Calculate":
        stock_conc = PREDEFINED_STOCK_CONC
        final_conc = values["-FINAL_CONC-"]
        cell_unit = values["-CELL_UNIT-"]
        final_vol = values["-FINAL_VOL-"]
        stock_unit = values["-STOCK_UNIT-"]
        final_unit = values["-FINAL_UNIT-"]

        result = calculate_dilution(final_conc, stock_conc, final_vol, cell_unit, stock_unit, final_unit)
        window["-RESULT-"].update(result)

# Close the window
window.close()
