# beihang
Running gait analysis for curved track

This GitHub has 2 code files. They are both python files.

To better understand the purpose of this Project, I will state overall objective and then describe why we used 2 different code files. There are multiple files other than the 2 python files which I will discuss in the overall objective below. 

    Overall Objective: We need to understand that our data comes from two different sources. We need to get positioning data from a ".gpx" file and ".csv" files for EMG and IMU.

    You should have 10 different EMG files. 

    Bicep Femoris (L)(R), Lattissimus Dorsi (L)(R), Erector Spinae (L)(R), Rectus Femoris (L)(R), Tibialis Anterior (L)(R)

    They should correspond to the names below

    BICEPS_FEM., LAT._GASTRO, LUMBAR_ES, RECTUS_FEM., TIB.ANT.

    Next, IMU files should be a total of 45 files. There are 5 different bones with each 9 different degrees of freedom (DoF). The bones are represented by a number. 11 is pelvis, 12 is left upper leg, 13 is right upper leg, 14 is left lower leg, 15 is right lower leg

The two code files we have are called masterScript.py and gait.py

masterScript.py is used to parse through our ".rar" file, which stores a compressed version of our ".csv" file. It also produced an output for our ".gpx" file which is now readable.  

masterScript.py has a total of 5 steps.

In the first step for ".gpx" processing it should be noted that on line 97, the keywords you see inside rows.append() ("lat", "lon", and "elevation_m") are arbitary labels. You are defining these keys yourself to build a new Python dictionary. They do not search the XML format inside the ".gpx" file for matching text.

masterScript.py should be opened in a text editor to see the description of what each step does. After step 2, we move on from processing the ".gpx" file and into extracting the compressed ".csv" files from our ".rar" file at step 3. 

Please keep in mind that if any future ".gpx" file is formatted in a different order then our code will not work.

For masterScript.py in step 3, we are only looking at file names. If our file names are missing keywords like "_Ax", "_Ay", "_Az", "_Gx", "_Gy", "_Gz", "_Mx", "_My", "_Mz" then we will not have files inside our "imu" folder. Everything else is moved to the the "emg" folder unless we decide it as irrelevant.

This detail can be found in line 246 in our masterScript.py

During step 4, we build off of step 2, we assume the "gpx" file began calculating time before our "emg" and "imu" data. So we use this step to synchronize the time to when they worked correctly together at the same time. 

Finally step 5 is where we combine the correct "IMU" to each bone. We have a complete data set of all 9 DoF in one ".csv" file.

masterScript.py is now finished.

We have just completed synchronization and organizing data. Next we will do gait analysis.

gait.py is how we will achieve creating an average gait cycle.

We must go to line 11 of gait.py to specify which bone file we are changing. If we follow the format of masterScript.py the file name will be "MATLAB_Ready_Running_Data_Full_##.csv"

The ## should be replaced to the appropriate number.

Running this script will also create gait cycle durations to know how each gait cycle different in time between each other. 

Please look at the images created and also the video link labeled "tutorial video" for more directions.

Make sure to download all packages in order to run script.

Use a package manager to download dependencies like Pip.

