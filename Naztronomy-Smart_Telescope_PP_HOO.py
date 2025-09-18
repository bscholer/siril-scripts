"""
(c) Nazmus Nasir 2025
SPDX-License-Identifier: GPL-3.0-or-later

Smart Telescope Preprocessing script
Version: 1.1.0
=====================================

The author of this script is Nazmus Nasir (Naztronomy) and can be reached at:
https://www.Naztronomy.com or https://www.YouTube.com/Naztronomy
Join discord for support and discussion: https://discord.gg/yXKqrawpjr
Support me on Patreon: https://www.patreon.com/c/naztronomy

The following directory is required inside the working directory:
    lights/

The following subdirectories are optional:
    darks/
    flats/
    biases/

"""

"""
CHANGELOG:

1.1.0 - Minor version update:
      - Added Batching support for 2000+ files on Windows
      - Removed Autocrop due to reported errors
      - Added support for Dwarf 2 and Celestron Origin
1.0.1 - minor refactoring to work with both .fit and .fits outputs (e.g. result.fit vs result.fits)
  - added support autocrop script created by Gottfried Rotter
1.0.0 - initial release
"""


import math
import shutil
import sirilpy as s

s.ensure_installed("ttkthemes", "numpy", "astropy")
from datetime import datetime
import time
import os
import sys
import tkinter as tk
from tkinter import ttk
from sirilpy import LogColor, NoImageError, tksiril
from ttkthemes import ThemedTk
from astropy.io import fits
import numpy as np

# Beta 3 
if sys.platform.startswith("linux"):
   import sirilpy.tkfilebrowser as filedialog
else:
   from tkinter import filedialog
# from tkinter import filedialog

APP_NAME = "Naztronomy - Smart Telescope Preprocessing"
VERSION = "1.1.0"
AUTHOR = "Nazmus Nasir"
WEBSITE = "Naztronomy.com"
YOUTUBE = "YouTube.com/Naztronomy"
TELESCOPES = [
    "ZWO Seestar S30",
    "ZWO Seestar S50",
    "Dwarf 3",
    "Dwarf 2",
    "Celestron Origin",
]

FILTER_OPTIONS_MAP = {
    "ZWO Seestar S30": ["No Filter (Broadband)", "LP (Narrowband)"],
    "ZWO Seestar S50": ["No Filter (Broadband)", "LP (Narrowband)"],
    "Dwarf 3": ["Astro filter (UV/IR)", "Dual-Band"],
    "Dwarf 2": ["Astro filter (UV/IR)"],
    "Celestron Origin": ["No Filter (Broadband)"],
}

FILTER_COMMANDS_MAP = {
    "ZWO Seestar S30": {
        "No Filter (Broadband)": ["-oscfilter=UV/IR Block"],
        "LP (Narrowband)": ["-oscfilter=ZWO Seestar LP"],
    },
    "ZWO Seestar S50": {
        "No Filter (Broadband)": ["-oscfilter=UV/IR Block"],
        "LP (Narrowband)": ["-oscfilter=ZWO Seestar LP"],
    },
    "Dwarf 3": {
        "Astro filter (UV/IR)": ["-oscfilter=UV/IR Block"],
        "Dual-Band": [
            "-narrowband",
            "-rwl=656.28",
            "-rbw=18",
            "-gwl=500.70",
            "-gbw=30",
            "-bwl=500.70",
            "-bbw=30",
        ],
    },
    "Dwarf 2": {"Astro filter (UV/IR)": ["-oscfilter=UV/IR Block"]},
    "Celestron Origin": {
        "No Filter (Broadband)": ["-oscfilter=UV/IR Block"],
    },
}


UI_DEFAULTS = {
    "feather_amount": 20.0,
    "drizzle_amount": 1.0,
    "pixel_fraction": 1.0,
    "max_files_per_batch": 2000,
}


class MacOSFriendlyDialog:
    def __init__(self, parent):
        self.parent = parent

    def askdirectory(self, **kwargs):
        """Dialogue de sélection de dossier optimisé pour macOS"""
        if sys.platform == "darwin":
            if self.parent:
                original_state = self.parent.state()

                self.parent.lift()
                self.parent.focus_force()
                self.parent.update_idletasks()

                kwargs_copy = kwargs.copy()
                if "parent" in kwargs_copy:
                    del kwargs_copy["parent"]

                result = filedialog.askdirectory(**kwargs_copy)

                if original_state == "normal":
                    self.parent.deiconify()
                self.parent.lift()

                return result

        return filedialog.askdirectory(**kwargs)


class PreprocessingInterface:

    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} - v{VERSION}")

        self.root.geometry(
            f"575x710+{int(self.root.winfo_screenwidth()/5)}+{int(self.root.winfo_screenheight()/5)}"
        )
        self.root.resizable(True, True)

        self.style = tksiril.standard_style()

        self.siril = s.SirilInterface()

        # Flags for mosaic mode and drizzle status
        # if drizzle is off, images will be debayered on convert
        self.drizzle_status = False
        self.drizzle_factor = 0

        self.spcc_section = ttk.LabelFrame()
        self.spcc_checkbox_variable = None
        self.chosen_telescope = "ZWO Seestar S30"
        self.telescope_options = TELESCOPES
        self.target_coords = None
        self.telescope_variable = tk.StringVar(value="ZWO Seestar S50")
        self.filter_variable = tk.StringVar(value="broadband")

        self.filter_options_map = FILTER_OPTIONS_MAP
        self.current_filter_options = self.filter_options_map[
            self.telescope_variable.get()
        ]
        self.filter_menu = None
        try:
            self.siril.connect()
            self.siril.log("Connected to Siril", LogColor.GREEN)
        except s.SirilConnectionError:
            self.siril.log("Failed to connect to Siril", LogColor.RED)
            self.close_dialog()
        tksiril.match_theme_to_siril(self.root, self.siril)
        try:
            self.siril.cmd("requires", "1.3.6")
        except s.CommandError:
            self.close_dialog()
            return

        self.fits_extension = self.siril.get_siril_config("core", "extension")

        self.gaia_catalogue_available = False
        try:
            catalog_status = self.siril.get_siril_config("core", "catalogue_gaia_astro")
            if (
                catalog_status
                and catalog_status != "(not set)"
                and os.path.isfile(catalog_status)
            ):
                self.gaia_catalogue_available = True

        except s.CommandError:
            pass
        self.current_working_directory = self.siril.get_siril_wd()
        self.cwd_label = tk.StringVar()

        # self.root.withdraw()  # Hide the main window
        changed_cwd = False  # a way not to run the prompting loop
        initial_cwd = os.path.join(self.current_working_directory, "lights")
        if os.path.isdir(initial_cwd):
            self.siril.log(
                f"Current working directory is valid: {self.current_working_directory}",
                LogColor.GREEN,
            )
            self.siril.cmd("cd", f'"{self.current_working_directory}"')
            self.cwd_label.set(
                f"Current working directory: {self.current_working_directory}"
            )
            changed_cwd = True
            # self.root.deiconify()
        elif os.path.basename(self.current_working_directory.lower()) == "lights":
            msg = "You're currently in the 'lights' directory, do you want to select the parent directory?"
            answer = tk.messagebox.askyesno("Already in Lights Dir", msg)
            if answer:
                self.siril.cmd("cd", "../")
                os.chdir(os.path.dirname(self.current_working_directory))
                self.current_working_directory = os.path.dirname(
                    self.current_working_directory
                )
                self.cwd_label.set(
                    f"Current working directory: {self.current_working_directory}"
                )
                self.siril.log(
                    f"Updated current working directory to: {self.current_working_directory}",
                    LogColor.GREEN,
                )
                changed_cwd = True
                # self.root.deiconify()
            else:
                self.siril.log(
                    f"Current working directory is invalid: {self.current_working_directory}, reprompting...",
                    LogColor.SALMON,
                )
                changed_cwd = False

        if not changed_cwd:
            dialog_helper = MacOSFriendlyDialog(self.root)

            while True:
                prompt_title = (
                    "Select the parent directory containing the 'lights' directory"
                )

                if sys.platform == "darwin":
                    self.root.lift()
                    self.root.attributes("-topmost", True)
                    self.root.update()
                    self.root.attributes("-topmost", False)

                selected_dir = dialog_helper.askdirectory(
                    initialdir=self.current_working_directory,
                    title=prompt_title,
                )

                if not selected_dir:
                    self.siril.log(
                        "Canceled selecting directory. Restart the script to try again.",
                        LogColor.SALMON,
                    )
                    self.siril.disconnect()
                    self.root.quit()
                    self.root.destroy()
                    break

                lights_directory = os.path.join(selected_dir, "lights")
                if os.path.isdir(lights_directory):
                    self.siril.cmd("cd", f'"{selected_dir}"')
                    os.chdir(selected_dir)
                    self.current_working_directory = selected_dir
                    self.cwd_label.set(f"Current working directory: {selected_dir}")
                    self.siril.log(
                        f"Updated current working directory to: {selected_dir}",
                        LogColor.GREEN,
                    )
                    break

                elif os.path.basename(selected_dir.lower()) == "lights":
                    msg = "The selected directory is the 'lights' directory, do you want to select the parent directory?"
                    answer = tk.messagebox.askyesno("Already in Lights Dir", msg)
                    if answer:
                        parent_dir = os.path.dirname(selected_dir)
                        self.siril.cmd("cd", f'"{parent_dir}"')
                        os.chdir(parent_dir)
                        self.current_working_directory = parent_dir
                        self.cwd_label.set(f"Current working directory: {parent_dir}")
                        self.siril.log(
                            f"Updated current working directory to: {parent_dir}",
                            LogColor.GREEN,
                        )
                        break
                else:
                    msg = f"The selected directory must contain a subdirectory named 'lights'.\nYou selected: {selected_dir}. Please try again."
                    self.siril.log(msg, LogColor.SALMON)
                    tk.messagebox.showerror("Invalid Directory", msg)
                    continue

        self.create_widgets()

    # Dirname: lights, darks, biases, flats
    def convert_files(self, dir_name, ha_oiii_mode=False):
        directory = os.path.join(self.current_working_directory, dir_name)
        if os.path.isdir(directory):
            self.siril.cmd("cd", dir_name)
            file_count = len(
                [
                    name
                    for name in os.listdir(directory)
                    if os.path.isfile(os.path.join(directory, name))
                ]
            )

            try:
                args = ["convert", dir_name, "-out=../process"]
                
                # Special handling for Ha/OIII extraction
                if ha_oiii_mode:
                    # For Ha/OIII extraction, lights must stay as CFA (no debayering)
                    # Calibration frames should also not be debayered to match
                    self.siril.log(f"Ha/OIII mode: converting {dir_name} without debayering", LogColor.BLUE)
                else:
                    # Regular workflow debayering logic
                    if "lights" in dir_name.lower():
                        if not self.drizzle_status:
                            args.append("-debayer")
                    else:
                        if not self.drizzle_status:
                            # flats, darks, bias: only debayer if drizzle is not set
                            args.append("-debayer")

                self.siril.log(" ".join(str(arg) for arg in args), LogColor.GREEN)
                self.siril.cmd(*args)
            except (s.DataError, s.CommandError, s.SirilError) as e:
                self.siril.log(f"File conversion failed: {e}", LogColor.RED)
                self.close_dialog()

            self.siril.cmd("cd", "../process")
            self.siril.log(
                f"Converted {file_count} {dir_name} files for processing!",
                LogColor.GREEN,
            )
        else:
            self.siril.error_messagebox(f"Directory {directory} does not exist", True)
            raise NoImageError(
                (
                    f'No directory named "{dir_name}" at this location. Make sure the working directory is correct.'
                )
            )

    # Plate solve on sequence runs when file count < 2048
    def seq_plate_solve(self, seq_name):
        """Runs the siril command 'seqplatesolve' to plate solve the converted files."""
        # self.siril.cmd("cd", "process")
        args = ["seqplatesolve", seq_name]

        # If origin or D2, need to pass in the focal length, pixel size, and target coordinates
        if self.chosen_telescope == "Celestron Origin":
            args.append(self.target_coords)
            focal_len = 400
            pixel_size = 2.4
            args.append(f"-focal={focal_len}")
            args.append(f"-pixelsize={pixel_size}")
        if self.chosen_telescope == "Dwarf 2":
            args.append(self.target_coords)
            focal_len = 100
            pixel_size = 1.45
            args.append(f"-focal={focal_len}")
            args.append(f"-pixelsize={pixel_size}")

        args.extend(["-nocache", "-force", "-disto=ps_distortion"])
        # args = ["platesolve", seq_name, "-disto=ps_distortion", "-force"]

        try:
            self.siril.cmd(*args)
        except (s.DataError, s.CommandError, s.SirilError) as e:
            self.siril.log(f"seqplatesolve failed: {e}", LogColor.RED)
            # self.siril.error_messagebox(f"seqplatesolve failed: {e}")
            # self.close_dialog()
        self.siril.log(f"Platesolved {seq_name}", LogColor.GREEN)

    def seq_bg_extract(self, seq_name):
        """Runs the siril command 'seqsubsky' to extract the background from the plate solved files."""
        try:
            self.siril.cmd("seqsubsky", seq_name, "1", "-samples=10")
        except (s.DataError, s.CommandError, s.SirilError) as e:
            self.siril.log(f"Seq BG Extraction failed: {e}", LogColor.RED)
            self.close_dialog()
        self.siril.log("Background extracted from Sequence", LogColor.GREEN)

    def seq_apply_reg(self, seq_name, drizzle_amount, pixel_fraction):
        """Apply Existing Registration to the sequence."""
        cmd_args = [
            "seqapplyreg",
            seq_name,
            "-filter-round=2.5k",
            # "-filter-fwhm=2k",
            "-kernel=square",
            "-framing=max",
        ]
        if self.drizzle_status:
            cmd_args.extend(
                ["-drizzle", f"-scale={drizzle_amount}", f"-pixfrac={pixel_fraction}"]
            )
        self.siril.log("Command arguments: " + " ".join(cmd_args), LogColor.BLUE)

        try:
            self.siril.cmd(*cmd_args)
        except (s.DataError, s.CommandError, s.SirilError) as e:
            self.siril.log(f"Data error occurred: {e}", LogColor.RED)

        self.siril.log("Registered Sequence", LogColor.GREEN)

    def extract_ha_oiii(self, seq_name):
        """Extract Ha and OIII channels from CFA sequence using seqextract_HaOIII."""
        try:
            self.siril.log(f"Extracting Ha and OIII from sequence: {seq_name}", LogColor.BLUE)
            self.siril.cmd("seqextract_HaOIII", seq_name)
            self.siril.log("Successfully extracted Ha and OIII channels", LogColor.GREEN)
            return f"Ha_{seq_name}", f"OIII_{seq_name}"
        except (s.DataError, s.CommandError, s.SirilError) as e:
            self.siril.log(f"Ha/OIII extraction failed: {e}", LogColor.RED)
            self.close_dialog()
            return None, None

    def process_narrowband_sequence(self, seq_name, drizzle_amount, pixel_fraction, is_ha_channel=False):
        """Process a narrowband sequence (Ha or OIII) with registration and stacking."""
        try:
            # Calculate appropriate drizzle factor
            # Ha channel needs 2x base drizzle to compensate for CFA extraction resolution loss
            if is_ha_channel:
                actual_drizzle = drizzle_amount * 2.0
                self.siril.log(f"Ha channel: applying {actual_drizzle}x drizzle (base {drizzle_amount}x × 2 for CFA compensation)", LogColor.BLUE)
            else:
                actual_drizzle = drizzle_amount
                self.siril.log(f"OIII channel: applying {actual_drizzle}x drizzle", LogColor.BLUE)
            
            # Plate solve the narrowband sequence
            self.seq_plate_solve(seq_name=seq_name)
            
            # Apply registration with appropriate drizzle factor
            self.seq_apply_reg(
                seq_name=seq_name,
                drizzle_amount=actual_drizzle,
                pixel_fraction=pixel_fraction,
            )
            
            # Stack the registered sequence
            registered_seq_name = f"r_{seq_name}"
            
            # Check for black frames if drizzle is enabled
            if self.drizzle_status:
                self.scan_black_frames(seq_name=registered_seq_name)
            
            self.seq_stack(
                seq_name=registered_seq_name,
                feather=False,  # No feathering needed for single channel
                feather_amount=0,
                rejection=True,
                output_name=seq_name.replace("_", "_result")
            )
            
            return f"{seq_name.replace('_', '_result')}"
            
        except (s.DataError, s.CommandError, s.SirilError) as e:
            self.siril.log(f"Narrowband sequence processing failed: {e}", LogColor.RED)
            return None

    def combine_ha_oiii(self, ha_image, oiii_image, output_name="HOO_result"):
        """Combine Ha and OIII images using RGB composition (HOO palette)."""
        try:
            self.siril.log("Combining Ha and OIII images into HOO composition", LogColor.BLUE)
            
            # Check and match dimensions first
            self.siril.log("Checking Ha and OIII image dimensions...", LogColor.BLUE)
            
            # Load Ha image and get its dimensions
            self.siril.cmd("load", ha_image)
            ha_img_data = self.siril.get_image()
            ha_width, ha_height = ha_img_data.width, ha_img_data.height
            
            # Load OIII image and get its dimensions  
            self.siril.cmd("load", oiii_image)
            oiii_img_data = self.siril.get_image()
            oiii_width, oiii_height = oiii_img_data.width, oiii_img_data.height
            
            self.siril.log(f"Ha dimensions: {ha_width}x{ha_height}", LogColor.BLUE)
            self.siril.log(f"OIII dimensions: {oiii_width}x{oiii_height}", LogColor.BLUE)
            
            # Get statistics for each channel to diagnose balance issues
            self.siril.cmd("load", ha_image)
            ha_img = self.siril.get_image()
            ha_stats = ha_img.stats
            
            # Handle different stats structure - could be list or object
            try:
                if isinstance(ha_stats, list) and len(ha_stats) > 0:
                    # If it's a list, use the first element (for single channel)
                    ha_mean = ha_stats[0].mean if hasattr(ha_stats[0], 'mean') else float(ha_stats[0])
                    ha_median = ha_stats[0].median if hasattr(ha_stats[0], 'median') else float(ha_stats[0])
                    ha_max = ha_stats[0].maximum if hasattr(ha_stats[0], 'maximum') else float(ha_stats[0])
                else:
                    # If it's an object with attributes
                    ha_mean = ha_stats.mean
                    ha_median = ha_stats.median
                    ha_max = ha_stats.maximum
            except:
                # Fallback: use numpy on pixel data directly
                ha_data = ha_img.data
                ha_mean = float(np.mean(ha_data))
                ha_median = float(np.median(ha_data))
                ha_max = float(np.max(ha_data))
            
            self.siril.log(f"Ha channel stats - Mean: {ha_mean:.3f}, Median: {ha_median:.3f}, Max: {ha_max:.3f}", LogColor.BLUE)
            
            self.siril.cmd("load", oiii_image) 
            oiii_img = self.siril.get_image()
            oiii_stats = oiii_img.stats
            
            # Handle different stats structure for OIII
            try:
                if isinstance(oiii_stats, list) and len(oiii_stats) > 0:
                    oiii_mean = oiii_stats[0].mean if hasattr(oiii_stats[0], 'mean') else float(oiii_stats[0])
                    oiii_median = oiii_stats[0].median if hasattr(oiii_stats[0], 'median') else float(oiii_stats[0])
                    oiii_max = oiii_stats[0].maximum if hasattr(oiii_stats[0], 'maximum') else float(oiii_stats[0])
                else:
                    oiii_mean = oiii_stats.mean
                    oiii_median = oiii_stats.median
                    oiii_max = oiii_stats.maximum
            except:
                # Fallback: use numpy on pixel data directly
                oiii_data = oiii_img.data
                oiii_mean = float(np.mean(oiii_data))
                oiii_median = float(np.median(oiii_data))
                oiii_max = float(np.max(oiii_data))
            
            self.siril.log(f"OIII channel stats - Mean: {oiii_mean:.3f}, Median: {oiii_median:.3f}, Max: {oiii_max:.3f}", LogColor.BLUE)
            
            # Additional debugging - check actual pixel data directly
            ha_data = ha_img.data
            oiii_data = oiii_img.data
            ha_direct_mean = float(np.mean(ha_data))
            oiii_direct_mean = float(np.mean(oiii_data))
            ha_nonzero_mean = float(np.mean(ha_data[ha_data > 0])) if np.any(ha_data > 0) else 0.0
            oiii_nonzero_mean = float(np.mean(oiii_data[oiii_data > 0])) if np.any(oiii_data > 0) else 0.0
            
            self.siril.log(f"Direct pixel analysis - Ha mean: {ha_direct_mean:.6f}, OIII mean: {oiii_direct_mean:.6f}", LogColor.BLUE)
            self.siril.log(f"Non-zero pixels - Ha mean: {ha_nonzero_mean:.6f}, OIII mean: {oiii_nonzero_mean:.6f}", LogColor.BLUE)
            
            # Auto-balance channels using direct pixel analysis
            # Use non-zero means for better comparison since many pixels might be black background
            ha_signal = ha_nonzero_mean if ha_nonzero_mean > 0 else ha_direct_mean
            oiii_signal = oiii_nonzero_mean if oiii_nonzero_mean > 0 else oiii_direct_mean
            
            balance_threshold = 1.5  # Lower threshold for normalized data
            ha_adjusted = ha_image
            oiii_adjusted = oiii_image
            
            if ha_signal > 0 and oiii_signal > 0:  # Avoid division by zero
                ha_to_oiii_ratio = oiii_signal / ha_signal
                
                self.siril.log(f"Signal ratio analysis - OIII/Ha = {ha_to_oiii_ratio:.3f}", LogColor.BLUE)
                
                if ha_to_oiii_ratio > balance_threshold:
                    # Ha is dimmer - boost it
                    boost_factor = min(ha_to_oiii_ratio * 0.8, 10.0)  # Higher cap for weak signals
                    self.siril.log(f"Ha channel is {ha_to_oiii_ratio:.2f}x dimmer than OIII, boosting by {boost_factor:.2f}x", LogColor.BLUE)
                    
                    self.siril.cmd("load", ha_image)
                    self.siril.cmd("mult", boost_factor)
                    ha_adjusted = f"{ha_image}_balanced"
                    self.siril.cmd("save", ha_adjusted)
                    
                elif ha_to_oiii_ratio < (1.0 / balance_threshold):
                    # OIII is dimmer - boost it  
                    boost_factor = min((1.0 / ha_to_oiii_ratio) * 0.8, 10.0)  # Higher cap for weak signals
                    self.siril.log(f"OIII channel is {1.0/ha_to_oiii_ratio:.2f}x dimmer than Ha, boosting by {boost_factor:.2f}x", LogColor.BLUE)
                    
                    self.siril.cmd("load", oiii_image)
                    self.siril.cmd("mult", boost_factor)
                    oiii_adjusted = f"{oiii_image}_balanced"
                    self.siril.cmd("save", oiii_adjusted)
                else:
                    self.siril.log("Channel balance looks reasonable - no adjustment needed", LogColor.GREEN)
            else:
                # If we can't measure signal properly, apply a moderate Ha boost as HOO often needs it
                self.siril.log("Unable to measure signal levels accurately - applying moderate Ha boost for HOO palette", LogColor.BLUE)
                self.siril.cmd("load", ha_image)
                self.siril.cmd("mult", 3.0)  # Moderate boost for typical HOO
                ha_adjusted = f"{ha_image}_balanced"
                self.siril.cmd("save", ha_adjusted)
            
            # Use the balanced images for further processing
            ha_image = ha_adjusted
            oiii_image = oiii_adjusted
            
            # If dimensions don't match, resize to common dimensions
            if ha_width != oiii_width or ha_height != oiii_height:
                self.siril.log("Dimension mismatch detected - resizing to common dimensions", LogColor.BLUE)
                
                # Use the smaller dimensions to avoid interpolation artifacts
                target_width = min(ha_width, oiii_width)
                target_height = min(ha_height, oiii_height)
                
                self.siril.log(f"Target dimensions: {target_width}x{target_height}", LogColor.BLUE)
                
                # Crop Ha image if needed (crop from center)
                if ha_width != target_width or ha_height != target_height:
                    self.siril.cmd("load", ha_image)
                    # Calculate crop area centered
                    crop_x = (ha_width - target_width) // 2
                    crop_y = (ha_height - target_height) // 2
                    self.siril.cmd("crop", crop_x, crop_y, target_width, target_height)
                    ha_image_cropped = f"{ha_image}_cropped"
                    self.siril.cmd("save", ha_image_cropped)
                    ha_image = ha_image_cropped
                    self.siril.log(f"Cropped Ha image to {target_width}x{target_height}", LogColor.BLUE)
                
                # Crop OIII image if needed (crop from center)
                if oiii_width != target_width or oiii_height != target_height:
                    self.siril.cmd("load", oiii_image)
                    # Calculate crop area centered
                    crop_x = (oiii_width - target_width) // 2
                    crop_y = (oiii_height - target_height) // 2
                    self.siril.cmd("crop", crop_x, crop_y, target_width, target_height)
                    oiii_image_cropped = f"{oiii_image}_cropped"
                    self.siril.cmd("save", oiii_image_cropped)
                    oiii_image = oiii_image_cropped
                    self.siril.log(f"Cropped OIII image to {target_width}x{target_height}", LogColor.BLUE)
            
            # Now combine with matching dimensions
            # HOO palette: Ha=Red, OIII=Green, OIII=Blue
            # This creates a palette similar to Hubble's SHO but using available narrowband channels
            self.siril.log("Creating HOO composition: Ha→Red, OIII→Green+Blue", LogColor.BLUE)
            self.siril.cmd("rgbcomp", ha_image, oiii_image, oiii_image, "-out=" + output_name)
            self.siril.log(f"Successfully created HOO composition: {output_name}", LogColor.GREEN)
            self.siril.log("Note: Very blue results may indicate weak Ha signal - consider manual channel balancing", LogColor.BLUE)
            return output_name
            
        except (s.DataError, s.CommandError, s.SirilError) as e:
            self.siril.log(f"HOO composition failed: {e}", LogColor.RED)
            return None

    def is_black_frame(self, data, threshold=10, crop_fraction=0.4):
        if data.ndim > 2:
            data = data[0]

        ny, nx = data.shape
        crop_x = int(nx * crop_fraction)
        crop_y = int(ny * crop_fraction)
        start_x = (nx - crop_x) // 2
        start_y = (ny - crop_y) // 2

        crop = data[start_y : start_y + crop_y, start_x : start_x + crop_x]
        nonzero = crop[crop != 0]

        if nonzero.size == 0:
            median_val = 0.0
        else:
            median_val = np.median(nonzero)

        return median_val < threshold, median_val

    def scan_black_frames(
        self, folder="process", threshold=30, crop_fraction=0.4, seq_name=None
    ):
        black_frames = []
        black_indices = []
        all_frames_info = []
        self.siril.log("Starting scan for black frames...", LogColor.BLUE)
        self.siril.log(
            "Note: This process is running in the background and may take a while depending on your system and drizzle factor.",
            LogColor.BLUE,
        )

        for idx, filename in enumerate(sorted(os.listdir(folder))):
            if filename.startswith(seq_name) and filename.lower().endswith(
                self.fits_extension
            ):
                filepath = os.path.join(folder, filename)
                try:
                    with fits.open(filepath) as hdul:
                        data = hdul[0].data
                        if data is not None and data.ndim >= 2:
                            dynamic_threshold = threshold
                            data_max = np.max(data)
                            if (
                                np.issubdtype(data.dtype, np.floating)
                                or data_max <= 10.0
                            ):
                                dynamic_threshold = 0.0001

                            is_black, median_val = self.is_black_frame(
                                data, dynamic_threshold, crop_fraction
                            )
                            all_frames_info.append((filename, median_val))

                            # Log for debugging
                            # print(
                            #     f"{filename} | shape: {data.shape} | dtype: {data.dtype} | min: {np.min(data)} | max: {data_max} | median: {median_val} | threshold used: {dynamic_threshold}"
                            # )

                            if is_black:
                                black_frames.append(filename)
                                black_indices.append(len(all_frames_info))
                        else:
                            self.siril.log(
                                f"{filename}: Unexpected data shape {data.shape if data is not None else 'None'}",
                                LogColor.SALMON,
                            )
                except Exception as e:
                    self.siril.log(f"Error reading {filename}: {e}", LogColor.RED)

        self.siril.log(f"Following files are black: {black_frames}", LogColor.SALMON)
        self.siril.log(
            f"Black indices skipped in stacking: {black_indices}", LogColor.SALMON
        )
        for index in black_indices:
            self.siril.cmd("unselect", seq_name, index, index)

    def calibration_stack(self, seq_name):
        # not in /process dir here
        if seq_name == "flats":
            if os.path.exists(
                os.path.join(
                    self.current_working_directory,
                    f"process/biases_stacked{self.fits_extension}",
                )
            ):
                # Saves as pp_flats
                self.siril.cmd("calibrate", "flats", "-bias=biases_stacked")
                self.siril.cmd(
                    "stack", "pp_flats rej 3 3", "-norm=mul", f"-out={seq_name}_stacked"
                )
                self.siril.cmd("cd", "..")
                return
            else:
                self.siril.cmd(
                    "stack",
                    f"{seq_name} rej 3 3",
                    "-norm=mul",
                    f"-out={seq_name}_stacked",
                )
                self.siril.cmd("cd", "..")
                return
        else:
            # Don't run code below for flats
            # biases and darks
            cmd_args = [
                "stack",
                f"{seq_name} rej 3 3 -nonorm",
                f"-out={seq_name}_stacked",
            ]
            self.siril.log(f"Running command: {' '.join(cmd_args)}", LogColor.BLUE)

            try:
                self.siril.cmd(*cmd_args)
            except (s.DataError, s.CommandError, s.SirilError) as e:
                self.siril.log(f"Command execution failed: {e}", LogColor.RED)
                self.close_dialog()

        self.siril.log(f"Completed stacking {seq_name}!", LogColor.GREEN)
        self.siril.cmd("cd", "..")

    def calibrate_lights(self, seq_name, use_darks=False, use_flats=False):
        cmd_args = [
            "calibrate",
            f"{seq_name}",
            "-dark=darks_stacked" if use_darks else "",
            "-flat=flats_stacked" if use_flats else "",
            "-cfa -equalize_cfa",
        ]

        try:
            self.siril.cmd(*cmd_args)
        except (s.DataError, s.CommandError, s.SirilError) as e:
            self.siril.log(f"Command execution failed: {e}", LogColor.RED)
            self.close_dialog()

    def seq_stack(
        self, seq_name, feather, feather_amount, rejection=False, output_name=None
    ):
        """Stack it all, and feather if it's provided"""
        out = "result" if output_name is None else output_name

        cmd_args = [
            "stack",
            f"{seq_name}",
            " rej 3 3" if rejection else " rej none",
            "-norm=addscale",
            "-output_norm",
            "-rgb_equal",
            "-maximize",
            "-filter-included",
            f"-out={out}",
        ]
        if feather:
            cmd_args.append(f"-feather={feather_amount}")

        self.siril.log(
            f"Running seq_stack with arguments:\n"
            f"seq_name={seq_name}\n"
            f"feather={feather}\n"
            f"feather_amount={feather_amount}",
            LogColor.BLUE,
        )

        self.siril.log(f"Running command: {' '.join(cmd_args)}", LogColor.BLUE)

        try:
            self.siril.cmd(*cmd_args)
        except (s.DataError, s.CommandError, s.SirilError) as e:
            self.siril.log(f"Stacking failed: {e}", LogColor.RED)
            self.close_dialog()

        self.siril.log(f"Completed stacking {seq_name}!", LogColor.GREEN)

    def save_image(self, suffix):
        """Saves the image as a FITS file."""

        current_datetime = datetime.now().strftime("%Y-%m-%d_%H%M")

        # Default filename
        drizzle_str = str(self.drizzle_factor).replace(".", "-")
        file_name = f"result__drizzle-{drizzle_str}x__{current_datetime}{suffix}"

        # Get header info from loaded image for filename
        current_fits_headers = self.siril.get_image_fits_header(return_as="dict")

        object_name = current_fits_headers.get("OBJECT", "Unknown").replace(" ", "_")
        exptime = int(current_fits_headers.get("EXPTIME", 0))
        stack_count = int(current_fits_headers.get("STACKCNT", 0))
        date_obs = current_fits_headers.get("DATE-OBS", current_datetime)

        try:
            dt = datetime.fromisoformat(date_obs)
            date_obs_str = dt.strftime("%Y-%m-%d")
        except ValueError:
            date_obs_str = datetime.now().strftime("%Y%m%d")

        file_name = f"{object_name}_{stack_count:03d}x{exptime}sec_{date_obs_str}"
        if self.drizzle_status:
            file_name += f"__drizzle-{drizzle_str}x"

        file_name += f"__{current_datetime}{suffix}"

        try:
            self.siril.cmd(
                "save",
                f"{file_name}",
            )
            return file_name
        except (s.DataError, s.CommandError, s.SirilError) as e:
            self.siril.log(f"Save command execution failed: {e}", LogColor.RED)
            self.close_dialog()
        self.siril.log(f"Saved file: {file_name}", LogColor.GREEN)

    def load_registered_image(self):
        """Loads the registered image. Currently unused"""
        try:
            self.siril.cmd("load", "result")
        except (s.DataError, s.CommandError, s.SirilError) as e:
            self.siril.log(f"Load command execution failed: {e}", LogColor.RED)
        self.save_image("_og")

    def image_plate_solve(self):
        """Plate solve the loaded image with the '-force' argument."""
        try:
            self.siril.cmd("platesolve", "-force")
        except (s.DataError, s.CommandError, s.SirilError) as e:
            self.siril.log(f"Plate Solve command execution failed: {e}", LogColor.RED)
            self.close_dialog()
        self.siril.log("Platesolved image", LogColor.GREEN)

    def spcc(
        self,
        oscsensor="ZWO Seestar S30",
        filter="No Filter (Broadband)",
        catalog="localgaia",
        whiteref="Average Spiral Galaxy",
    ):
        if oscsensor == "Unistellar Evscope 2":
            self.siril.cmd("pcc", f"-catalog={catalog}")
            self.siril.log(
                "PCC'd Image, SPCC Unavailable for Evscope 2", LogColor.GREEN
            )
        else:
            recoded_sensor = oscsensor
            """SPCC with oscsensor, filter, catalog, and whiteref."""
            if oscsensor in ["Dwarf 3"]:
                recoded_sensor = "Sony IMX678"
            else:
                recoded_sensor = oscsensor

            args = [
                f"-oscsensor={recoded_sensor}",
                f"-catalog={catalog}",
                f"-whiteref={whiteref}",
            ]

            # Add filter-specific arguments
            filter_args = FILTER_COMMANDS_MAP.get(oscsensor, {}).get(filter)
            if filter_args:
                args.extend(filter_args)
            else:
                # Default to UV/IR Block
                args.append("-oscfilter=UV/IR Block")

            # Double Quote each argument due to potential spaces
            quoted_args = [f'"{arg}"' for arg in args]
            try:
                self.siril.cmd("spcc", *quoted_args)
            except (s.CommandError, s.DataError, s.SirilError) as e:
                self.siril.log(f"SPCC execution failed: {e}", LogColor.RED)
                self.close_dialog()

            img = self.save_image("_spcc")
            self.siril.log(f"Saved SPCC'd image: {img}", LogColor.GREEN)
            return img

    def load_image(self, image_name):
        """Loads the result."""
        try:
            self.siril.cmd("load", image_name)
        except (s.DataError, s.CommandError, s.SirilError) as e:
            self.siril.log(f"Load image failed: {e}", LogColor.RED)
            self.close_dialog()
        self.siril.log(f"Loaded image: {image_name}", LogColor.GREEN)

    def autostretch(self, do_spcc):
        """Autostretch as a way to preview the final result"""
        try:
            self.siril.cmd("autostretch", *(["-linked"] if do_spcc else []))
        except (s.DataError, s.CommandError, s.SirilError) as e:
            self.siril.log(f"Autostretch command execution failed: {e}", LogColor.RED)

            self.close_dialog()
        self.siril.log(
            "Autostretched image."
            + (" You may want to open the _spcc file instead." if do_spcc else ""),
            LogColor.GREEN,
        )

    def clean_up(self, prefix=None):
        """Cleans up all files in the process directory."""
        if not self.current_working_directory.endswith("process"):
            process_dir = os.path.join(self.current_working_directory, "process")
        else:
            process_dir = self.current_working_directory
        for f in os.listdir(process_dir):
            # Skip the stacked file
            name, ext = os.path.splitext(f.lower())
            if name in (f"{prefix}_stacked", "result") and ext in (self.fits_extension):
                continue

            # Check if file starts with prefix_ or pp_flats_
            if (
                f.startswith(prefix)
                or f.startswith(f"{prefix}_")
                or f.startswith("pp_flats_")
            ):
                file_path = os.path.join(process_dir, f)
                if os.path.isfile(file_path):
                    # print(f"Removing: {file_path}")
                    os.remove(file_path)
        self.siril.log(f"Cleaned up {prefix}", LogColor.BLUE)

    # Function to update filter options
    def update_filter_options(self, *args):
        selected_scope = self.telescope_variable.get()
        new_options = self.filter_options_map.get(selected_scope, [])
        # self.siril.log(selected_scope, LogColor.BLUE)
        self.chosen_telescope = selected_scope
        self.siril.log(f"Chosen Telescope: {selected_scope}", LogColor.BLUE)
        # Clear current menu
        menu = self.filter_menu["menu"]
        menu.delete(0, "end")

        # Add new options
        for option in new_options:
            menu.add_command(
                label=option,
                command=lambda value=option: self.filter_variable.set(value),
            )

        # Set default and enable menu
        self.filter_variable.set(new_options[0])
        state = tk.NORMAL if self.spcc_checkbox_variable.get() else tk.DISABLED
        self.filter_menu["state"] = state

    def show_help(self):
        help_text = (
            f"Author: {AUTHOR} ({WEBSITE})\n"
            f"Youtube: {YOUTUBE}\n"
            "Discord: https://discord.gg/yXKqrawpjr\n"
            "Patreon: https://www.patreon.com/c/naztronomy\n\n"
            "Info:\n"
            '1. Must have a "lights" subdirectory inside of the working directory.\n'
            "2. For Calibration frames, you can have one or more of the following types: darks, flats, biases.\n"
            f"3. If on Windows and you have more than {UI_DEFAULTS['max_files_per_batch']} files, this script will automatically split them into batches.\n"
            "4. If batching, intermediary files are cleaned up automatically even if 'clean up files' is unchecked.\n"
            "5. If batching, the frames are automatically feathered during the final stack even if 'feather' is unchecked.\n"
            "6. Ha/OIII extraction automatically applies 2x additional drizzle to Ha channel for resolution recovery.\n"
            "7. If Ha/OIII is enabled, drizzle is automatically enabled with minimum 1.0x factor.\n"
            "8. Ha/OIII extraction keeps all frames as CFA (no debayering) to preserve channel data.\n"
            "9. HOO palette maps Ha→Red, OIII→Green+Blue. Very blue results indicate weak Ha signal.\n"
            "10. Script automatically balances channels if one is 3x dimmer than the other.\n"
            "11. Drizzle increases processing time. Higher the drizzle the longer it takes.\n"
            "12. When asking for help, please have the logs handy."
        )
        self.siril.info_messagebox(help_text, True)
        self.siril.log(help_text, LogColor.BLUE)

        tksiril.elevate(self.root)

    def create_widgets(self):
        """Creates the UI widgets."""
        main_frame = ttk.Frame(self.root, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True, anchor=tk.NW)

        # Define styles
        bold_label = ttk.Style()
        bold_label.configure("Bold.TLabel", font=("TkDefaultFont", 10, "bold"))

        # Title and version
        ttk.Label(
            main_frame,
            text=f"{APP_NAME}",
            style="Bold.TLabel",
            font=("Segoe UI", 10, "bold"),
        ).pack(pady=(10, 10))

        ttk.Label(
            main_frame,
            textvariable=self.cwd_label,
        ).pack(anchor="w", pady=(0, 10))

        # Telescope section
        telescope_section = ttk.LabelFrame(main_frame, text="Telescope", padding=10)
        telescope_section.pack(fill=tk.X, pady=5)
        ttk.Label(telescope_section, text="Telescope:", style="Bold.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        ttk.OptionMenu(
            telescope_section,
            self.telescope_variable,
            "ZWO Seestar S30",
            *self.telescope_options,
        ).grid(row=0, column=1, columnspan=3, sticky="w", padx=5, pady=5)

        self.telescope_variable.trace_add("write", self.update_filter_options)

        # Optional Calibration Frames
        ttk.Label(
            telescope_section, text="Calibration Frames:", style="Bold.TLabel"
        ).grid(row=1, column=0, sticky="w")

        darks_checkbox_variable = tk.BooleanVar()
        ttk.Checkbutton(
            telescope_section, text="Darks", variable=darks_checkbox_variable
        ).grid(row=1, column=1, sticky="w", padx=5, pady=10)

        flats_checkbox_variable = tk.BooleanVar()
        ttk.Checkbutton(
            telescope_section, text="Flats", variable=flats_checkbox_variable
        ).grid(row=1, column=2, sticky="w", padx=5)

        biases_checkbox_variable = tk.BooleanVar()
        ttk.Checkbutton(
            telescope_section, text="Biases", variable=biases_checkbox_variable
        ).grid(row=1, column=3, sticky="w", padx=5)

        ttk.Label(telescope_section, text="Clean Up Files:", style="Bold.TLabel").grid(
            row=2, column=0, sticky="w"
        )

        cleanup_files_checkbox_variable = tk.BooleanVar()
        cleanup_checkbox = ttk.Checkbutton(
            telescope_section, text="", variable=cleanup_files_checkbox_variable
        )
        cleanup_checkbox.grid(row=2, column=1, sticky="w", padx=5)
        tksiril.create_tooltip(
            cleanup_checkbox,
            "Enable this option to delete all intermediary files after they are done processing. This saves space on your hard drive.\n"
            "Note: If your session is batched, this option is automatically enabled even if it's unchecked!",
        )

        # Optional Preprocessing Steps
        calib_section = ttk.LabelFrame(
            main_frame, text="Optional Preprocessing Steps", padding=10
        )

        calib_section.pack(fill=tk.X, pady=5)
        ttk.Label(
            calib_section, text="Background Extraction:", style="Bold.TLabel"
        ).grid(row=2, column=0, sticky="w")

        bg_extract_checkbox_variable = tk.BooleanVar()
        ttk.Checkbutton(
            calib_section,
            text="",
            variable=bg_extract_checkbox_variable,
        ).grid(row=2, column=1, sticky="w")

        ttk.Label(calib_section, text="Ha/OIII Processing:", style="Bold.TLabel").grid(
            row=3, column=0, sticky="w"
        )

        haoiii_checkbox_variable = tk.BooleanVar()
        haoiii_checkbox = ttk.Checkbutton(
            calib_section, text="Extract Ha/OIII", variable=haoiii_checkbox_variable
        )
        haoiii_checkbox.grid(row=3, column=1, sticky="w")
        tksiril.create_tooltip(
            haoiii_checkbox,
            "Extract Ha/OIII channels from dual-band filter images.\n"
            "Creates HOO palette similar to Hubble SHO.\n"
            "Useful for narrowband imaging with OSC cameras.",
        )

        ttk.Label(calib_section, text="Registration:", style="Bold.TLabel").grid(
            row=4, column=0, sticky="w"
        )

        drizzle_checkbox_variable = tk.BooleanVar()
        drizzle_checkbox = ttk.Checkbutton(
            calib_section, text="Drizzle?", variable=drizzle_checkbox_variable
        )
        drizzle_checkbox.grid(row=4, column=1, sticky="w")
        tksiril.create_tooltip(
            drizzle_checkbox,
            "Drizzle upsamples images during registration to recover resolution.\n"
            "For Ha/OIII extraction: drizzle is automatically enabled with Ha getting 2x additional drizzle for resolution recovery."
        )

        drizzle_amount_label = ttk.Label(calib_section, text="Drizzle amount:")
        drizzle_amount_label.grid(row=4, column=2, sticky="w")
        drizzle_amount_variable = tk.DoubleVar(value=UI_DEFAULTS["drizzle_amount"])
        drizzle_amount_spinbox = ttk.Spinbox(
            calib_section,
            textvariable=drizzle_amount_variable,
            from_=0.1,
            to=3.0,
            increment=0.1,
            state=tk.DISABLED,
        )
        drizzle_amount_spinbox.grid(row=4, column=3, sticky="w")
        drizzle_checkbox_variable.trace_add(
            "write",
            lambda *args: drizzle_amount_spinbox.config(
                state=tk.NORMAL if drizzle_checkbox_variable.get() else tk.DISABLED,
                textvariable=drizzle_amount_variable,
            ),
        )
        ttk.Label(calib_section, text="Pixel Fraction:").grid(
            row=5, column=2, sticky="w"
        )
        pixel_fraction_variable = tk.DoubleVar(value=UI_DEFAULTS["pixel_fraction"])
        pixel_fraction_spinbox = ttk.Spinbox(
            calib_section,
            textvariable=pixel_fraction_variable,
            from_=0.1,
            to=10.0,
            increment=0.01,
            state=tk.DISABLED,
        )
        pixel_fraction_spinbox.grid(row=5, column=3, sticky="w")
        drizzle_checkbox_variable.trace_add(
            "write",
            lambda *args: pixel_fraction_spinbox.config(
                state=tk.NORMAL if drizzle_checkbox_variable.get() else tk.DISABLED,
                textvariable=pixel_fraction_variable,
            ),
        )

        ttk.Label(calib_section, text="Stacking:", style="Bold.TLabel").grid(
            row=6, column=0, sticky="w"
        )

        feather_checkbox_variable = tk.BooleanVar()
        feather_checkbox = ttk.Checkbutton(
            calib_section, text="Feather?", variable=feather_checkbox_variable
        )
        feather_checkbox.grid(row=6, column=1, sticky="w")

        feather_amount_label = ttk.Label(calib_section, text="Feather amount:")
        feather_amount_label.grid(row=6, column=2, sticky="w")
        feather_amount_variable = tk.DoubleVar(value=UI_DEFAULTS["feather_amount"])
        feather_amount_spinbox = ttk.Spinbox(
            calib_section,
            textvariable=feather_amount_variable,
            from_=5,
            to=2000,
            increment=5,
            state=tk.DISABLED,
        )
        feather_amount_spinbox.grid(row=6, column=3, sticky="w")
        feather_checkbox_variable.trace_add(
            "write",
            lambda *args: feather_amount_spinbox.config(
                state=tk.NORMAL if feather_checkbox_variable.get() else tk.DISABLED,
                textvariable=feather_amount_variable,
            ),
        )

        # SPCC Section
        self.spcc_section = ttk.LabelFrame(main_frame, text="Post-Stacking", padding=10)
        self.spcc_section.pack(fill=tk.X, pady=5)

        self.spcc_checkbox_variable = tk.BooleanVar()

        def toggle_filter_and_gaia():
            state = tk.NORMAL if self.spcc_checkbox_variable.get() else tk.DISABLED
            self.filter_menu["state"] = state
            catalog_menu["state"] = state

        ttk.Checkbutton(
            self.spcc_section,
            text="Enable Spectrophotometric Color Calibration (SPCC)",
            variable=self.spcc_checkbox_variable,
            command=toggle_filter_and_gaia,
        ).grid(row=1, column=0, columnspan=2, sticky="w")

        ttk.Label(self.spcc_section, text="OSC Filter:", style="Bold.TLabel").grid(
            row=2, column=0, sticky="w"
        )

        # filter_options = ["broadband", "narrowband"]
        self.filter_menu = ttk.OptionMenu(
            self.spcc_section,
            self.filter_variable,
            "No Filter (Broadband)",
            *self.current_filter_options,
        )
        self.filter_menu.grid(row=2, column=1, sticky="w")
        self.filter_menu["state"] = tk.DISABLED

        ttk.Label(self.spcc_section, text="Catalog:", style="Bold.TLabel").grid(
            row=3, column=0, sticky="w"
        )
        catalog_variable = tk.StringVar(value="localgaia")
        catalog_options = ["localgaia", "gaia"]
        catalog_menu = ttk.OptionMenu(
            self.spcc_section, catalog_variable, "localgaia", *catalog_options
        )
        catalog_menu.grid(row=3, column=1, sticky="w")
        catalog_menu["state"] = tk.DISABLED

        if self.gaia_catalogue_available:
            ttk.Label(
                self.spcc_section,
                text="✓ Local Gaia Available",
                foreground="green",
                style="Success.TLabel",
            ).grid(row=3, column=2, sticky="w")
        else:
            ttk.Label(
                self.spcc_section, text="✗ Local Gaia Not available", foreground="red"
            ).grid(row=3, column=2, sticky="w")

        ttk.Button(main_frame, text="Help", width=10, command=self.show_help).pack(
            pady=(15, 0), side=tk.LEFT
        )

        # Run button
        ttk.Button(
            main_frame,
            text="Run",
            width=10,
            command=lambda: self.run_script(
                do_spcc=self.spcc_checkbox_variable.get(),
                filter=self.filter_variable.get(),
                telescope=self.telescope_variable.get(),
                catalog=catalog_variable.get(),
                use_darks=darks_checkbox_variable.get(),
                use_flats=flats_checkbox_variable.get(),
                use_biases=biases_checkbox_variable.get(),
                bg_extract=bg_extract_checkbox_variable.get(),
                ha_oiii_extract=haoiii_checkbox_variable.get(),
                drizzle=drizzle_checkbox_variable.get(),
                drizzle_amount=float(drizzle_amount_spinbox.get()),
                pixel_fraction=float(pixel_fraction_spinbox.get()),
                feather=feather_checkbox_variable.get(),
                feather_amount=float(feather_amount_spinbox.get()),
                clean_up_files=cleanup_files_checkbox_variable.get(),
            ),
        ).pack(pady=(15, 0), side=tk.RIGHT)

        # Close button
        ttk.Button(main_frame, text="Close", width=10, command=self.close_dialog).pack(
            pady=(15, 0), side=tk.RIGHT
        )

    def close_dialog(self):
        self.siril.disconnect()
        self.root.quit()
        self.root.destroy()

    def extract_coords_from_fits(self, prefix: str):
        # Only process for specific D2 and Origin
        process_dir = "process"
        matching_files = sorted(
            [
                f
                for f in os.listdir(process_dir)
                if f.startswith(prefix) and f.lower().endswith(self.fits_extension)
            ]
        )

        if not matching_files:
            self.siril.log(
                f"No FITS files found in '{process_dir}' with prefix '{prefix}'",
                LogColor.RED,
            )
            return

        first_file = matching_files[0]
        print(first_file)
        file_path = os.path.join(process_dir, first_file)

        try:
            with fits.open(file_path) as hdul:
                header = hdul[0].header
                ra = header.get("RA")
                dec = header.get("DEC")

                if ra is not None and dec is not None:
                    self.target_coords = f"{ra},{dec}"
                    self.siril.log(
                        f"Target coordinates extracted: {self.target_coords}",
                        LogColor.GREEN,
                    )
                else:
                    self.siril.log(
                        "RA or DEC not found in FITS header.", LogColor.SALMON
                    )
        except Exception as e:
            self.siril.log(f"Error reading FITS header: {e}", LogColor.RED)

    def batch(
        self,
        output_name: str,
        use_darks: bool = False,
        use_flats: bool = False,
        use_biases: bool = False,
        bg_extract: bool = False,
        drizzle: bool = False,
        drizzle_amount: float = UI_DEFAULTS["drizzle_amount"],
        pixel_fraction: float = UI_DEFAULTS["pixel_fraction"],
        feather: bool = False,
        feather_amount: float = UI_DEFAULTS["feather_amount"],
        clean_up_files: bool = False,
    ):
        # If we're batching, force cleanup files so we don't collide with existing files
        self.siril.cmd("close")
        if output_name.startswith("batch_lights"):
            clean_up_files = True

        self.drizzle_status = drizzle
        self.drizzle_factor = drizzle_amount

        # Output name is actually the name of the batched working directory
        self.convert_files(dir_name=output_name, ha_oiii_mode=False)  # Regular batching always uses normal mode
        self.unselect_bad_fits(seq_name=output_name)

        seq_name = f"{output_name}_"

        # self.siril.cmd("cd", batch_working_dir)

        # Using calibration frames puts pp_ prefix in process directory
        if use_flats or use_darks:
            self.calibrate_lights(
                seq_name=seq_name, use_darks=use_darks, use_flats=use_flats
            )
            seq_name = "pp_" + seq_name

        if bg_extract:
            self.seq_bg_extract(seq_name=seq_name)
            if clean_up_files:
                self.clean_up(
                    prefix=seq_name
                )  # Remove "pp_lights_" or just "lights_" if not flat calibrated
            seq_name = "bkg_" + seq_name

        if self.chosen_telescope in ["Celestron Origin", "Dwarf 2"]:
            self.extract_coords_from_fits(prefix=seq_name)

        self.seq_plate_solve(seq_name=seq_name)
        # seq_name stays the same after plate solve
        self.seq_apply_reg(
            seq_name=seq_name,
            drizzle_amount=drizzle_amount,
            pixel_fraction=pixel_fraction,
        )
        if clean_up_files:
            self.clean_up(
                prefix=seq_name
            )  # Clean up bkg_ files or pp_ if flat calibrated, otherwise lights_
        seq_name = f"r_{seq_name}"

        if drizzle:
            self.scan_black_frames(seq_name=seq_name)

        self.seq_stack(
            seq_name=seq_name,
            feather=feather,
            feather_amount=feather_amount,
            rejection=True,
            output_name=output_name,
        )

        if clean_up_files:
            self.clean_up(prefix=seq_name)  # clean up r_ files

        # Load the result (e.g. batch_lights_001.fits)
        self.load_image(image_name=output_name)
        # Go back to working dir
        self.siril.cmd("cd", "../")

        # Save og image in WD - might have drizzle factor in name
        if output_name.startswith("batch_lights"):
            out = output_name
        else:
            out = "og"
        file_name = self.save_image(f"_{out}")

        return file_name

    def process_ha_oiii_workflow(
        self,
        use_darks: bool = False,
        use_flats: bool = False,
        use_biases: bool = False,
        bg_extract: bool = False,
        drizzle: bool = False,
        drizzle_amount: float = UI_DEFAULTS["drizzle_amount"],
        pixel_fraction: float = UI_DEFAULTS["pixel_fraction"],
        clean_up_files: bool = False,
    ):
        """Process images using Ha/OIII extraction workflow."""
        self.siril.log("Starting Ha/OIII extraction workflow", LogColor.GREEN)
        
        # For Ha/OIII extraction, drizzle is essential for Ha resolution recovery
        # Use minimum 1.0x drizzle even if user didn't enable drizzle
        effective_drizzle_amount = max(drizzle_amount, 1.0) if not drizzle else drizzle_amount
        
        # Always enable drizzle for Ha/OIII workflow
        original_drizzle_status = self.drizzle_status
        self.drizzle_status = True
        
        if not drizzle and effective_drizzle_amount == 1.0:
            self.siril.log("Ha/OIII extraction requires drizzle - automatically enabling 1.0x base drizzle", LogColor.BLUE)
        
        # Process calibration frames and lights
        lights_directory = "lights"
        
        # Convert lights first - keep as CFA for Ha/OIII extraction
        self.convert_files(dir_name=lights_directory, ha_oiii_mode=True)
        self.unselect_bad_fits(seq_name=lights_directory)

        seq_name = f"{lights_directory}_"

        # Using calibration frames puts pp_ prefix in process directory
        if use_flats or use_darks:
            try:
                self.calibrate_lights(
                    seq_name=seq_name, use_darks=use_darks, use_flats=use_flats
                )
                seq_name = "pp_" + seq_name
                self.siril.log("Calibration successful with CFA frames", LogColor.GREEN)
            except (s.DataError, s.CommandError, s.SirilError) as e:
                self.siril.log(f"Calibration failed: {e}", LogColor.SALMON)
                self.siril.log("Ha/OIII extraction continuing without calibration", LogColor.BLUE)
                self.siril.log("Tip: For Ha/OIII extraction, calibration frames work best when captured with same settings", LogColor.BLUE)
                # Continue without calibration - seq_name stays as lights_

        if bg_extract:
            self.seq_bg_extract(seq_name=seq_name)
            if clean_up_files:
                self.clean_up(prefix=seq_name)
            seq_name = "bkg_" + seq_name

        # Extract Ha and OIII channels
        self.siril.log("Extracting Ha and OIII channels...", LogColor.BLUE)
        ha_seq, oiii_seq = self.extract_ha_oiii(seq_name=seq_name)
        
        if ha_seq is None or oiii_seq is None:
            self.siril.log("Ha/OIII extraction failed, aborting", LogColor.RED)
            return None

        # Clean up original sequence if requested
        if clean_up_files:
            self.clean_up(prefix=seq_name)

        # Process Ha sequence (with automatic 2x drizzle compensation)
        self.siril.log("Processing Ha sequence...", LogColor.BLUE)
        ha_result = self.process_narrowband_sequence(
            seq_name=ha_seq,
            drizzle_amount=effective_drizzle_amount,
            pixel_fraction=pixel_fraction,
            is_ha_channel=True,
        )

        # Process OIII sequence  
        self.siril.log("Processing OIII sequence...", LogColor.BLUE)
        oiii_result = self.process_narrowband_sequence(
            seq_name=oiii_seq,
            drizzle_amount=effective_drizzle_amount,
            pixel_fraction=pixel_fraction,
            is_ha_channel=False,
        )

        if ha_result is None or oiii_result is None:
            self.siril.log("Narrowband processing failed", LogColor.RED)
            return None

        # Clean up intermediate files
        if clean_up_files:
            self.clean_up(prefix=ha_seq)
            self.clean_up(prefix=f"r_{ha_seq}")
            self.clean_up(prefix=oiii_seq)
            self.clean_up(prefix=f"r_{oiii_seq}")

        # Combine Ha and OIII into HOO image
        self.siril.log("Combining Ha and OIII into HOO composition...", LogColor.BLUE)
        hoo_result = self.combine_ha_oiii(ha_result, oiii_result, "HOO_result")
        
        if hoo_result is None:
            self.siril.log("HOO composition failed", LogColor.RED)
            return None

        # Load the final HOO image
        self.load_image(image_name=hoo_result)
        
        # Go back to working directory
        self.siril.cmd("cd", "../")
        
        # Save the result
        final_file_name = self.save_image("_HOO")
        self.siril.log(f"Ha/OIII workflow completed successfully: {final_file_name}", LogColor.GREEN)
        
        # Restore original drizzle status
        self.drizzle_status = original_drizzle_status
        
        return final_file_name

    def unselect_bad_fits(self, seq_name, folder="process"):
        """
        Checks all FITS files in the given folder with the given prefix
        for integrity and unselects any bad ones in the current sequence
        in Siril.

        Parameters
        ----------
        seq_name : str
            The prefix of the sequence to check.
        folder : str, optional
            The folder to check for FITS files. Defaults to "process".

        Returns
        -------
        None
        """
        self.siril.log("Checking for bad FITS files...", LogColor.BLUE)
        bad_fits = []
        all_files = sorted(
            [
                f
                for f in os.listdir(folder)
                if f.startswith(seq_name) and f.lower().endswith(self.fits_extension)
            ]
        )
        for idx, filename in enumerate(all_files):
            file_path = os.path.join(folder, filename)
            try:
                with fits.open(file_path) as hdul:
                    _ = hdul[0].data  # Try to access data

            except Exception as e:
                self.siril.log(f"Bad FITS file: {filename} — {e}", LogColor.SALMON)
                bad_fits.append(idx + 1)  # Siril indices start at 1

        if bad_fits:
            self.siril.log(f"Unselecting bad frames: {bad_fits}", LogColor.SALMON)
            for index in bad_fits:
                try:
                    self.siril.cmd("unselect", seq_name, index, index)
                except Exception as e:
                    self.siril.log(
                        f"Failed to unselect index {index}: {e}", LogColor.RED
                    )
        else:
            self.siril.log("No bad FITS files found.", LogColor.GREEN)

    def run_script(
        self,
        do_spcc: bool = False,
        filter: str = "broadband",
        telescope: str = "ZWO Seestar S30",
        catalog: str = "localgaia",
        use_darks: bool = False,
        use_flats: bool = False,
        use_biases: bool = False,
        bg_extract: bool = False,
        ha_oiii_extract: bool = False,
        drizzle: bool = False,
        drizzle_amount: float = UI_DEFAULTS["drizzle_amount"],
        pixel_fraction: float = UI_DEFAULTS["pixel_fraction"],
        feather: bool = False,
        feather_amount: float = UI_DEFAULTS["feather_amount"],
        clean_up_files: bool = False,
    ):
        self.siril.log(
            f"Running script version {VERSION} with arguments:\n"
            f"do_spcc={do_spcc}\n"
            f"filter={filter}\n"
            f"telescope={telescope}\n"
            f"catalog={catalog}\n"
            f"use_darks={use_darks}\n"
            f"use_flats={use_flats}\n"
            f"use_biases={use_biases}\n"
            f"bg_extract={bg_extract}\n"
            f"ha_oiii_extract={ha_oiii_extract}\n"
            f"drizzle={drizzle}\n"
            f"drizzle_amount={drizzle_amount}\n"
            f"pixel_fraction={pixel_fraction}\n"
            f"feather={feather}\n"
            f"feather_amount={feather_amount}\n"
            f"clean_up_files={clean_up_files}",
            LogColor.BLUE,
        )
        self.siril.cmd("close")
        # Check files - if more than 2048, batch them:
        self.drizzle_status = drizzle
        self.drizzle_factor = drizzle_amount

        # TODO: Stack calibration frames and copy to the various batch dirs
        if use_biases:
            self.convert_files("biases", ha_oiii_mode=ha_oiii_extract)
            self.calibration_stack("biases")
            if clean_up_files:
                self.clean_up("biases")
        if use_flats:
            self.convert_files("flats", ha_oiii_mode=ha_oiii_extract)
            self.calibration_stack("flats")
            if clean_up_files:
                self.clean_up("flats")
        if use_darks:
            self.convert_files("darks", ha_oiii_mode=ha_oiii_extract)
            self.calibration_stack("darks")
            if clean_up_files:
                self.clean_up("darks")

        # Check files in working directory/lights.
        # create sub folders with more than 2048 divided by equal amounts

        lights_directory = "lights"

        # Get list of all files in the lights directory
        all_files = [
            name
            for name in os.listdir(lights_directory)
            if os.path.isfile(os.path.join(lights_directory, name))
        ]
        num_files = len(all_files)
        is_windows = sys.platform.startswith("win")

        # Check if Ha/OIII extraction is enabled
        if ha_oiii_extract:
            self.siril.log("Ha/OIII extraction enabled - using narrowband workflow", LogColor.BLUE)
            file_name = self.process_ha_oiii_workflow(
                use_darks=use_darks,
                use_flats=use_flats,
                use_biases=use_biases,
                bg_extract=bg_extract,
                drizzle=drizzle,
                drizzle_amount=drizzle_amount,
                pixel_fraction=pixel_fraction,
                clean_up_files=clean_up_files,
            )
            if file_name is None:
                self.siril.log("Ha/OIII workflow failed", LogColor.RED)
                return
            self.load_image(image_name=file_name)
        # only one batch will be run if less than max_files_per_batch OR not windows.
        elif num_files <= UI_DEFAULTS["max_files_per_batch"] or not is_windows:
            self.siril.log(
                f"{num_files} files found in the lights directory which is less than or equal to {UI_DEFAULTS['max_files_per_batch']} files allowed per batch - no batching needed.",
                LogColor.BLUE,
            )
            file_name = self.batch(
                output_name=lights_directory,
                use_darks=use_darks,
                use_flats=use_flats,
                use_biases=use_biases,
                bg_extract=bg_extract,
                drizzle=drizzle,
                drizzle_amount=drizzle_amount,
                pixel_fraction=pixel_fraction,
                feather=feather,
                feather_amount=feather_amount,
                clean_up_files=clean_up_files,
            )

            self.load_image(image_name=file_name)
        else:
            num_batches = math.ceil(num_files / UI_DEFAULTS["max_files_per_batch"])
            batch_size = math.ceil(num_files / num_batches)

            self.siril.log(
                f"{num_files} files found in the lights directory, splitting into {num_batches} batches...",
                LogColor.BLUE,
            )

            # Ensure temp folders exist and are empty
            for i in range(num_batches):
                batch_dir = f"batch_lights{i+1}"
                os.makedirs(batch_dir, exist_ok=True)
                # Optionally clean out existing files:
                for f in os.listdir(batch_dir):
                    os.remove(os.path.join(batch_dir, f))

            # Split and copy files into batches
            for i, filename in enumerate(all_files):
                batch_index = i // UI_DEFAULTS["max_files_per_batch"]
                batch_dir = f"batch_lights{batch_index + 1}"
                src_path = os.path.join(lights_directory, filename)
                dest_path = os.path.join(batch_dir, filename)
                shutil.copy2(src_path, dest_path)

            # Send each of the new lights dir into batch directory
            for i in range(num_batches):
                batch_dir = f"batch_lights{i+1}"
                self.siril.log(f"Processing batch: {batch_dir}", LogColor.BLUE)
                self.batch(
                    output_name=batch_dir,
                    use_darks=use_darks,
                    use_flats=use_flats,
                    use_biases=use_biases,
                    bg_extract=bg_extract,
                    drizzle=drizzle,
                    drizzle_amount=drizzle_amount,
                    pixel_fraction=pixel_fraction,
                    feather=feather,
                    feather_amount=feather_amount,
                    clean_up_files=clean_up_files,
                )
            self.siril.log("Batching complete.", LogColor.GREEN)

            # Create batched_lights directory
            final_stack_seq_name = "final_stack"
            batch_lights = "batch_lights"
            os.makedirs(final_stack_seq_name, exist_ok=True)
            source_dir = os.path.join(os.getcwd(), "process")
            # Move batch result files into batched_lights
            target_subdir = os.path.join(os.getcwd(), final_stack_seq_name)

            # Create the target subdirectory if it doesn't exist
            os.makedirs(target_subdir, exist_ok=True)

            # Loop through all files in the source directory
            for filename in os.listdir(source_dir):
                if f"{batch_lights}" in filename:
                    full_src_path = os.path.join(source_dir, filename)
                    full_dst_path = os.path.join(target_subdir, filename)

                # Only move files, skip directories
                if os.path.isfile(full_src_path):
                    shutil.move(full_src_path, full_dst_path)
                    self.siril.log(f"Moved: {filename}", LogColor.BLUE)

            # Clean up temp_lightsX directories
            for i in range(num_batches):
                batch_dir = f"{batch_lights}{i+1}"
                shutil.rmtree(batch_dir, ignore_errors=True)

            self.convert_files(final_stack_seq_name, ha_oiii_mode=False)  # Batching final stack uses normal mode
            self.seq_plate_solve(seq_name=final_stack_seq_name)
            # turn off drizzle for this
            self.drizzle_status = False
            self.seq_apply_reg(
                seq_name=final_stack_seq_name,
                drizzle_amount=drizzle_amount,
                pixel_fraction=pixel_fraction,
            )
            self.clean_up(prefix=final_stack_seq_name)
            registered_final_stack_seq_name = f"r_{final_stack_seq_name}"
            # final stack needs feathering and amount
            self.drizzle_status = drizzle  # Turn drizzle back to selected option
            self.seq_stack(
                seq_name=registered_final_stack_seq_name,
                feather=True,
                rejection=False,
                feather_amount=60,
                output_name="final_result",
            )
            self.load_image(image_name="final_result")

            # cleanup final_stack directory
            shutil.rmtree(final_stack_seq_name, ignore_errors=True)
            self.clean_up(prefix=registered_final_stack_seq_name)

            # Go back to working dir
            self.siril.cmd("cd", "../")

            # Save og image in WD - might have drizzle factor in name
            file_name = self.save_image("_batched")

        # Spcc as a last step
        if do_spcc:
            # For Ha/OIII workflow, SPCC may not be as applicable since it's already a processed composite
            if ha_oiii_extract:
                self.siril.log("SPCC is typically not applied to HOO composite images", LogColor.SALMON)
            else:
                img = self.spcc(
                    oscsensor=telescope,
                    filter=filter,
                    catalog=catalog,
                    whiteref="Average Spiral Galaxy",
                )

                # self.autostretch(do_spcc=do_spcc)
                if drizzle:
                    img = os.path.basename(img) + self.fits_extension
                else:
                    img = os.path.basename(img)
                self.load_image(
                    image_name=os.path.basename(img)
                )  # Load either og or spcc image

        # self.clean_up()
        import datetime

        self.siril.log(
            f"Finished at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            LogColor.GREEN,
        )
        self.siril.log(
            """
        Thank you for using the Naztronomy Smart Telescope Preprocessor! 
        The author of this script is Nazmus Nasir (Naztronomy).
        Website: https://www.Naztronomy.com 
        YouTube: https://www.YouTube.com/Naztronomy 
        Discord: https://discord.gg/yXKqrawpjr
        Patreon: https://www.patreon.com/c/naztronomy
        """,
            LogColor.BLUE,
        )

        self.close_dialog()


def main():
    try:
        root = ThemedTk()
        app = PreprocessingInterface(root)
        root.mainloop()
    except Exception as e:
        print(f"Error initializing application: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()


##############################################################################

# Website: https://www.Naztronomy.com
# YouTube: https://www.YouTube.com/Naztronomy
# Discord: https://discord.gg/yXKqrawpjr
# Patreon: https://www.patreon.com/c/naztronomy

##############################################################################
