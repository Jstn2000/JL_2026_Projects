***THE PLAN***

1 Convert pictures to paint by number pictures.
2 Functionality to paint the generated picture.



**STEPS I**

1.1 Search for a given path to find all images in a directory
1.2 Choose a image from the directory to process
1.3 Let the user choose the pixel size and the color range
1.4 Show a preview of the image to the user
1.6 Option to start painting

2.1 UI for painting
2.2 Display the image
2.3 Use the users mouse as a brush tool


==> We use python.
    --> We use the tkinter module for the ui
    --> We use os module for extracting to png files (1.1.1)

==> Preselection ui (1.2.1)
==> Menubar (1.3.1)
==> Previewscreen (1.4.1)
==> Tabsystem to swap between image choice and image paint mode (1.6.1)
==> Menubar on the left of the paint screen (2.1.1)
==> Big main space for displaying the image (2.2.1)
==> User contols via the keyboard module and the mouse module from pygames


**STEPS II**

1.1 Search for a given path to find all images in a directory
    1.1.1 We use os module for extracting to png files
1.2 Choose a image from the directory to process
    1.2.1 Preselection ui
1.3 Let the user choose the pixel size and the color range
    1.3.1 Menubar
        1.3.1.1 Element for directory selection
        1.3.1.2 Element for closing the application
        1.3.1.3 Element for pixilating the image
        1.3.1.4 Element for saving the image
        1.3.1.5 Textfields for entering pixel size
        1.3.1.6 Textfield for entering number of different colors
1.4 Show a preview of the image to the user
    1.4.1 Previewscreen
    1.4.2 Pixelate the image
1.6 Option to start painting
    1.6.1 Tabsystem to swap between image choice and image paint mode
        1.6.1.1 A main window for the general controls (Open, close)
        1.6.1.2 A system to switch between paint and image pixelate screen


2.1 UI for painting
    2.1.1 Menubar on the left of the paint screen
        2.1.1.1 A button for every color that is then selected as the brush color
        2.1.1.2 A small textfield beneath its color that shows its number in the painting
        2.1.1.3 A button to switch between fill and single pixel mode
        (2.1.1.4 A button to change to magic pencil that swaps colors in automatic mode)
2.2 Display the image
    2.2.1 Big main space for displaying the image
        2.2.1.1 A zoom contol for the painting screen
        2.2.1.2 Movement controls to move the image in the painting screen
2.3 Use the users mouse as a brush tool
    2.3.1 Track mouse position on the painting screen relativ to the picture
    2.4.2 Keep track of the selected color


==> A list of all png options with a preview of the image and there title beneath (1.2.1.1)
==> A slider and mouse scroll option for the image choice (1.2.1.2)


**STEPS III**

1.1 Search for a given path to find all images in a directory
    1.1.1 We use os module for extracting to png files
1.2 Choose a image from the directory to process
    1.2.1 Preselection ui
        1.2.1.1 A list of all png options with a preview of the image and there title beneath
        1.2.1.2 A slider and mouse scroll option for the image choice
1.3 Let the user choose the pixel size and the color range
    1.3.1 Menubar
        1.3.1.1 Element for directory selection
        1.3.1.2 Element for closing the application
        1.3.1.3 Element for pixilating the image
        1.3.1.4 Element for saving the image
        1.3.1.5 Textfields for entering pixel size
        1.3.1.6 Textfield for entering number of different colors
1.4 Show a preview of the image to the user
    1.4.1 Previewscreen
    1.4.2 Pixelate the image
1.6 Option to start painting
    1.6.1 Tabsystem to swap between image choice and image paint mode
        1.6.1.1 A main window for the general controls (Open, close)
        1.6.1.2 A system to switch between paint and image pixelate screen


2.1 UI for painting
    2.1.1 Menubar on the left of the paint screen
        2.1.1.1 A button for every color that is then selected as the brush color
        2.1.1.2 A small textfield beneath its color that shows its number in the painting
        2.1.1.3 A button to switch between fill and single pixel mode
        (2.1.1.4 A button to change to magic pencil that swaps colors in automatic mode)
2.2 Display the image
    2.2.1 Big main space for displaying the image
        2.2.1.1 A zoom contol for the painting screen
        2.2.1.2 Movement controls to move the image in the painting screen
2.3 Use the users mouse as a brush tool
    2.3.1 Track mouse position on the painting screen relativ to the picture
    2.4.2 Keep track of the selected color
