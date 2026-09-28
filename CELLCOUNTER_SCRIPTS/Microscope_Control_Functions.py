import openflexure_microscope_client as ofm_client
from PIL import Image ## Needed for saving PIL image objects - note: PIL is same as Pillow package


## only runs in Python 3.7
## Width of FOV in X ~= 8400 not exact - may cause the image centre to drift over time - perhaps will cause issues
## Width of FOV in Y ~= 6400 - as above
## Z should be autofocused regardless - only one autofocus is fine
## microscope is the object class for interacting with microscope

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
    
def main():
    Image_Acquisition()
    
if __name__ == '__main__':
    main()





