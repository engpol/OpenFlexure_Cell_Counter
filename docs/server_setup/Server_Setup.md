# OFM Cell Counter Server Setup



## Introduction



This guide will cover how to setup a server to run CellPose models for improved cell segmentation on the OFM Cell Counter. Screenshots will be provided for most steps, but unless otherwise stated, **all** of the commands presented here will have to be ran in terminal on the server. 

Time: about 2-3 hours

---

## 0: Before you start…


What you will require:

### Hardware

- Any PC (from roughly the last 10 years), 8 GB RAM, ~20 GB free disk.
- A spare Ethernet port. A USB-Ethernet adapter works.
- An ordinary Ethernet cable.
- An NVIDIA GPU in the PC. This is **optional,** but speeds up model run-time. See step 3.
- USB Stick - at least 8 GB - for installing Linux on the server

### OS Setup

This guide assumes the server is running **Xubuntu 24.04 LTS** (or Lubuntu / Linux Mint XFCE — any works). Download: [https://xubuntu.org/download/](https://xubuntu.org/download/). It is recommended to do a fresh install of this on the PC. Please see the [following guide](https://docs.xubuntu.org/user/pt/installation.html) on how to install XUbuntu onto any PC (You will need an empty USB stick with at least 8 GB of storage space).

During installation, note the username you create. This guide uses `jlserver`; I recommend sticking with this during installation, if you change it, you may have to substitute it in any commands that are run.

**Temporary internet access is required** for steps 2–4 (package downloads and the CellPose model weights). After setup the server needs no internet.

Once you have installed Xubuntu on your server and have internet access, continue

---

## **1. Get the files onto the server**


Open up terminal on your server:

![SS2.png](/.git/images/SS2.png)

In the terminal, run the following code. You can copy it from this block, paste it in the terminal and press Enter.  This will copy all required files from the repo onto the server.

```python
sudo apt update
sudo apt install -y git
git clone https:/.git.com/engpol/OpenFlexure_Cell_Counter.git ~/cell_counter_repo
cd ~/cell_counter_repo/SERVER_FILES
```

![Image_1.png](/.git/images/Image_1.png)

---

## 2: Install Python via Miniforge



Now run the following command block inside the terminal to install Python onto the server. 

```python
wget https:/.git.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh -b -p "$HOME/miniforge3"
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda init bash
```

(Some SS of what this should look like)

![SS5.png](/.git/images/SS5.png)

![SS6.png](/.git/images/SS6.png)

Now Close and reopen the terminal, then run the following code block to create the virtual environment which will run the python code. 

```python
cd ~/cell_counter_repo/SERVER_FILES
conda create -n cellcount python=3.10 -y
conda activate cellcount
```

![SS7.png](/.git/images/SS7.png)

![SS8.png](/.git/images/SS8.png)

Your terminal prompt should now start with `(cellcount)`. 

![SS9.png](/.git/images/751d836c-e26c-44b8-bc86-98e45d000a53.png)

**It must stay active for steps 3 and 4**. If you close the terminal for any reason, you will have to restart the environment by running `conda activate cellcount` again.

---

## **3. Install PyTorch**



**This step will decide whether the NVIDIA GPU (If you have one) is used, or whether code should be run on the CPU.** 

Following one of the following steps based on if you have an NVIDIA GPU or not.

### No NVIDIA GPU:

Run this command to install the CPU version of PyTorch.

```python
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

### NVIDIA GPU:

First check what you have by running this command:

```python
nvidia-smi
```

![SS3.png](/.git/images/SS3.png)

Even if you have an NVIDIA GPU, you may have to install nvidia-sma. Install it using one of the commands suggested in the terminal. Then run `nvidia-smi` again.

![SS4.png](/.git/images/SS4.png)

Check "CUDA Version" (shown in the screen shot above in the top-right by `nvidia-smi`).

In the commands below, make sure your wheel index no higher than it (`cu126`, `cu128` or `cu130`). I.e. if your CUDA version is 13.0, you should use `cu130` or below. 

Or,  more simply, use the table below to install compatible drivers based the generation of NVIDIA GPU you have. Copy the appropriate command and run it in terminal as before. 

| GPU generation | Install |
| --- | --- |
| Pascal (GTX 10-series)  | `pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu126` |
| Turing or newer (RTX 20/30/40/50, GTX 16) | `pip install torch --index-url https://download.pytorch.org/whl/cu128` |

### **BOTH: Install other requirements and verify either path**

After finishing one of the above to setup Pytorch, run the following command in terminal. 

**IMPORTANT**: Make sure you are in the SERVER_FILES directory which contains a lot of the setup files - (enter using `cd ~/cell_counter_repo/SERVER_FILES`). 
If you aren't in the directory, this command and a lot of the ones below will fail. 

```bash
pip install -r requirements.txt
python check_gpu.py
```

![Image_4.png](/.git/images/Image_4.png)

This installs other required python packages, and prints whether the GPU will actually be used, and if not, exactly why.

![Image_3.png](/.git/images/Image_3.png)

---

## 4. **Download the CellPose model weights**



CellPose fetches its weights on first use. You can skip this step if the server will have internet access at all times. However, this can be required in case your server may lose internet access after moving it closer to the cell counter (my server does not have wifi-capability for example). 

Run the following command in terminal

```python
python fetch_models.py --download
python fetch_models.py --check
```

From now on, you will need your OFM Cell Counter at hand.

---

## **5. Configure the network link**



Connect the server and OFM Cell Counter using an Ethernet cable then run the following command to find the interface name:

```python
ip link
```

(I used ip addr show, but it should look similar)

![SS16.png](/.git/images/cecc4ce0-3759-47e4-a8b4-1ed04ca285d2.png)

Look for a wired interface — `enp3s0`, `eno1`, or similar. Not `lo`, and not whichever one carries your normal network. For me, this was eno1. To test this, you can unplug the ethernet, and see which interface dissapears. Keep a note of this name.

I will show two ways of setting up the networking between the server and the OFM Cell Counter. One is using the GUI, and one is by running a code block in command line. 

### **Option A — Graphical**

1. Run `nm-connection-editor` in terminal to open up the networking GUI

![SS16.png](/.git/images/SS16.png)

2. Select the wired connection for the interface identified above, click the gear icon.

![SS17.png](/.git/images/SS17.png)

3. **IPv4 Settings** → Method: **Manual**.

![SS18.png](/.git/images/SS18.png)

4. **Add**: Address `192.168.50.10`, Netmask `255.255.255.0`, Gateway **empty**.

![SS19.png](/.git/images/SS19.png)

5. Click **Routes…** and tick **"Use this connection only for resources on its own network."**

![SS20.png](/.git/images/SS20.png)

6. Save.

### Option B - Command Line

If you’d prefer to avoid using the GUI, run this code block in terminal. 

**IMPORTANT:** Replace `eno1` in the code block below with your interface name! 

```python
sudo nmcli con add type ethernet ifname eno1 con-name direct-link \
  ipv4.method manual \
  ipv4.addresses 192.168.50.10/24 \
  ipv4.never-default yes \
  ipv4.dns-priority 200
sudo nmcli con up direct-link
```

### Verify

Run the following code block to verify the connection is working as expected. Again replace `eno1` in the code block below with your interface name! 

```python
ip addr show eno1      # expect: inet 192.168.50.10/24
ip route | grep default  # expect: ONE default route, NOT via eno1
ping -c 3 192.168.50.1   # the Pi should answer
```

What this should look like:

![6371d020-8838-4bba-a195-ddbd175656eb.png](/.git/images/6371d020-8838-4bba-a195-ddbd175656eb.png)

---

## **7. Install the Worker (Get the server up and running!)**


Now, run the following script, which should for the most part finish the setup for the server.

```python
sudo bash install_service.sh
```

![Image_6.png](/.git/images/Image_6.png)

In case you are wondering the script does the following:

- finds your conda Python and checks cellpose, fastapi and uvicorn import
- copies the files to `/opt/cell_counter`
- creates a numba cache directory
- writes the systemd unit with your real username and paths
- enables and starts the service which waits for images from the Pi, runs cellpose models on them to generate masks, and returns them back to the Pi.

The setup should now be complete, however a few verification steps.

---

## **8. Verify the server**



Now run the following commands in the terminal on the server, to make sure everything is working as expected. 

```python
systemctl is-enabled cellcounter-worker   # expect: enabled
systemctl is-active  cellcounter-worker   # expect: active
curl http://192.168.50.10:8000/health
```

The last one should returns something like:

```python
{"status":"ok","model":"cyto2","device":"gpu","loaded":true,"auth_required":true, ...}
```

You may have to wait ~30 s after finishing step 7, for the worker to be up and running. If the curl command does not return the expected result, try again after some time. 

---

## 9. Verify the Cell Counter



**Now on the Cell Counter**: make sure that the cell counter can communicate with the server by running the same command as above in terminal on the cell counter:

```python
curl http://192.168.50.10:8000/health
```

If you see the same response as before: 

```python
{"status":"ok","model":"cyto2","device":"gpu","loaded":true,"auth_required":true, ...}
```

Then the Cell Counter should now be able to use the server for Cellpose segmentation! 

---

## 10. Final Test: Reboot the Server


As a final test, while the server and Cell Counter are still connected, restart the server. 

After about 30s, run the `curl [http://192.168.50.10:8000/health](http://192.168.50.10:8000/health)` command again. If this gets a response, it means the server setup is finished. It can boot up on its own, and can be turned on/off at will. 

---

## Optional: Using custom trained Cellpose Models

---

Getting the server to use custom trained cellpose models is very simple.

**ONLY** If this is your first time adding a custom model to the cell counter, run the following code on the server to make a folder to keep all your custom models in:

```python
sudo mkdir -p /opt/cell_counter/models
sudo chown -R $USER:$USER /opt/cell_counter/models
```

### Changing Models:

Using a USB stick or whichever way you’d like, move the model file for the model you’d like to use into the /opt/cell_counter/models folder. If you would like to use the model I trained on HEK-293 cells, you can find it in the [CELLPOSE_MODELS](/CELLPOSE_MODELS/) directory.

Then, to make the server use this custom model instead of the default cyto2:

First run this:

```python
sudo systemctl edit --full cellcounter-worker
```
![Image_9.png](/.git/images/Image_9.png)

In the file that opens up, change the “CELLCOUNT_MODEL” to point to your custom model, e.g. “CP_20260916_120000”. Remember to also change the cellpose diameter "CELLCOUNT_DIAMETER" to whichever diam the model was trained on! 

```python
Environment=CELLCOUNT_MODEL=/opt/cell_counter/models/CP_20260916_120000
```


Then, to restart the server and make sure it is now using your model:

```python
sudo systemctl daemon-reload
sudo systemctl restart cellcounter-worker
journalctl -u cellcounter-worker -n 20 --no-pager
```

The log should confirm `Loading CUSTOM model:` and print the diameter the model was trained at. `/health` will show `"model_is_custom": true`.