#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import os
import platform
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# Third-party imports
try:
    import serial.tools.list_ports
except ImportError:
    messagebox.showerror(
        "Dependency Error",
        "pyserial library not found.\nPlease install it: pip install pyserial"
    )
    exit()

# Optional UI Enhancement (Theme)
try:
    import sv_ttk
except ImportError:
    messagebox.showwarning(
        "Theme Error",
        "sv-ttk theme library not found.\nFalling back to default theme."
        "\nInstall using: pip install sv-ttk"
    )
    sv_ttk = None

# DPI Awareness setup for Windows for sharper GUI on High-DPI screens
try:
    import ctypes
    if platform.system() == "Windows":
        # Constants for DPI awareness levels
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        # PROCESS_SYSTEM_DPI_AWARE = 1
        # PROCESS_DPI_UNAWARE = 0
        # Try setting Per Monitor v2 DPI awareness
        error_code = ctypes.windll.shcore.SetProcessDpiAwareness(2)
        if error_code != 0:  # S_OK = 0 indicates success
            # Fallback to System Aware for older Windows versions
            error_code = ctypes.windll.user32.SetProcessDPIAware()
            if error_code == 0:
                print("Warning: SetProcessDpiAwareness failed, "
                      "fallback SetProcessDPIAware also failed.")
except ImportError:
    print("Warning: ctypes module not found, cannot set DPI awareness.")
except AttributeError:
    # This can happen if the specific functions aren't available
    print("Warning: Could not set DPI awareness (API not found). "
          "GUI might appear blurry on High-DPI screens.")
except Exception as e:
    print(f"Warning: An error occurred while setting DPI awareness: {e}")

# Import the backend radio communication class and constants
try:
    from tef_radio_comms import (
        TEF_ESP32_Radio, ALL_BANDWIDTHS, FM_BANDWIDTHS, AM_BANDWIDTHS,
        CSV_HEADER
    )
except ImportError:
    messagebox.showerror(
        "Import Error",
        "Could not find tef_radio_comms.py.\n"
        "Make sure the file containing the TEF_ESP32_Radio class "
        "is in the same directory."
    )
    exit()
except Exception as e:
    messagebox.showerror(
        "Import Error",
        f"An error occurred importing tef_radio_comms.py:\n{e}"
    )
    exit()

# --- Constants ---
DEFAULT_BAUD = 115200
BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]
APP_TITLE = "TEF Radio Memory Manager"
APP_VERSION = "1.0.4"
APP_AUTHOR = "antonioag95"
APP_DATE = "10-04-25"
APP_ICON_FILENAME = "tef_icon.png"

# --- Resource Path Function ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        # Note: In newer PyInstaller versions, _MEIPASS might be an attribute
        # on sys directly. hasattr is a safe check.
        if hasattr(sys, '_MEIPASS'):
            # Running in a PyInstaller bundle
            base_path = sys._MEIPASS
        else:
             # Running in a normal Python environment
            base_path = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        # Fallback to current working directory if unsure.
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# --- Font Selection ---
# Choose platform-specific default fonts for better native look and feel
DEFAULT_FONT_FAMILY = "Segoe UI" if platform.system() == "Windows" else \
                      "Cantarell" if platform.system() == "Linux" else \
                      "San Francisco"  # Default for macOS/other
DEFAULT_FONT_SIZE = 10
DEFAULT_FONT = (DEFAULT_FONT_FAMILY, DEFAULT_FONT_SIZE)
TREEVIEW_FONT = (DEFAULT_FONT_FAMILY, DEFAULT_FONT_SIZE - 1)
HEADING_FONT = (DEFAULT_FONT_FAMILY, DEFAULT_FONT_SIZE, "bold")


# --- Edit Channel Dialog ---
class WriteChannelDialog(tk.Toplevel):
    """Dialog window for editing or creating radio channel presets."""

    def __init__(self, parent, radio_instance, initial_data=None):
        """
        Initialize the dialog.

        Args:
            parent: The parent window (main application).
            radio_instance: An instance of TEF_ESP32_Radio for context.
            initial_data (dict, optional): Data for the channel being edited.
                                           If None, it's a new channel entry.
        """
        super().__init__(parent)
        self.parent = parent
        self.radio = radio_instance
        self.initial_data = initial_data

        self.title("Edit Channel")
        self.resizable(False, False)
        self.transient(parent)  # Keep dialog on top of parent
        self.grab_set()         # Make dialog modal

        self.result_data = None  # Stores validated data if user clicks OK
        self.current_band = "Unknown"  # Track detected band (AM/FM)

        # Bandwidth mappings for display and conversion
        self.bw_code_to_text_fm = FM_BANDWIDTHS
        self.bw_code_to_text_am = AM_BANDWIDTHS
        self.fm_text_to_code = {v: k for k, v in FM_BANDWIDTHS.items()}
        self.am_text_to_code = {v: k for k, v in AM_BANDWIDTHS.items()}

        # Create sorted lists of bandwidth text values for comboboxes
        # Sorting by the underlying code ensures logical order (e.g., Auto first)
        self.fm_bw_values = sorted(
            FM_BANDWIDTHS.values(),
            key=lambda text_val: self.fm_text_to_code[text_val]
        )
        self.am_bw_values = sorted(
            AM_BANDWIDTHS.values(),
            key=lambda text_val: self.am_text_to_code[text_val]
        )
        # Combine and sort all possible bandwidth values
        self.all_bw_values = sorted(
            list(set(self.fm_bw_values) | set(self.am_bw_values)),
            key=lambda text_val: self.fm_text_to_code.get(
                text_val, self.am_text_to_code.get(text_val, float('inf'))
            )
        )

        # Form variables linked to input fields
        self.ch_var = tk.StringVar()
        self.freq_var = tk.StringVar()
        self.bw_text_var = tk.StringVar()
        self.mono_stereo_var = tk.StringVar()
        self.pi_var = tk.StringVar()
        self.ps_var = tk.StringVar()

        # Update bandwidth options dynamically when frequency changes
        self.freq_var.trace_add("write", self._on_frequency_change)

        # Input validation commands for length limits
        vcmd_4 = (self.register(self._validate_length), '%P', 4)  # Max 4 chars
        vcmd_8 = (self.register(self._validate_length), '%P', 8)  # Max 8 chars

        # Create UI elements
        frame = ttk.Frame(self, padding="15")
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Channel #:").grid(
            row=0, column=0, sticky="w", padx=5, pady=7
        )
        self.ch_entry = ttk.Entry(frame, textvariable=self.ch_var, width=5)
        self.ch_entry.grid(row=0, column=1, sticky="w", padx=5, pady=7)

        ttk.Label(frame, text="Frequency:").grid(
            row=1, column=0, sticky="w", padx=5, pady=7
        )
        self.freq_entry = ttk.Entry(
            frame, textvariable=self.freq_var, width=15
        )
        self.freq_entry.grid(
            row=1, column=1, columnspan=2, sticky="w", padx=5, pady=7
        )
        ttk.Label(frame, text="(e.g., 101.7MHz, 980kHz, 90.2, 1020)").grid(
            row=1, column=3, sticky="w", padx=5, pady=7
        )

        ttk.Label(frame, text="Bandwidth:").grid(
            row=2, column=0, sticky="w", padx=5, pady=7
        )
        self.bw_combo = ttk.Combobox(
            frame, textvariable=self.bw_text_var, width=12,
            state=tk.DISABLED,  # Initially disabled until freq is valid
            values=self.all_bw_values
        )
        self.bw_combo.grid(
            row=2, column=1, columnspan=2, sticky="w", padx=5, pady=7
        )

        ttk.Label(frame, text="Mode:").grid(
            row=3, column=0, sticky="w", padx=5, pady=7
        )
        self.ms_combo = ttk.Combobox(
            frame, textvariable=self.mono_stereo_var,
            values=["Mono", "Stereo"], width=12, state="readonly"
        )
        self.ms_combo.grid(
            row=3, column=1, columnspan=2, sticky="w", padx=5, pady=7
        )

        ttk.Label(frame, text="PI Code:").grid(
            row=4, column=0, sticky="w", padx=5, pady=7
        )
        self.pi_entry = ttk.Entry(
            frame, textvariable=self.pi_var, width=6,
            validate='key', validatecommand=vcmd_4  # Validate on key press
        )
        self.pi_entry.grid(row=4, column=1, sticky="w", padx=5, pady=7)
        ttk.Label(frame, text="(Max 4 hex)").grid(
            row=4, column=2, sticky="w", padx=5, pady=7
        )

        ttk.Label(frame, text="PS Text:").grid(
            row=5, column=0, sticky="w", padx=5, pady=7
        )
        self.ps_entry = ttk.Entry(
            frame, textvariable=self.ps_var, width=10,
            validate='key', validatecommand=vcmd_8  # Validate on key press
        )
        self.ps_entry.grid(
            row=5, column=1, columnspan=2, sticky="w", padx=5, pady=7
        )
        ttk.Label(frame, text="(Max 8 chars)").grid(
            row=5, column=3, sticky="w", padx=5, pady=7
        )

        # OK and Cancel buttons
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=6, column=0, columnspan=4, pady=15)
        ok_button = ttk.Button(
            button_frame, text="OK",
            command=self._validate_and_accept, style="Accent.TButton"
        )
        ok_button.pack(side=tk.LEFT, padx=10)
        cancel_button = ttk.Button(
            button_frame, text="Cancel", command=self.destroy
        )
        cancel_button.pack(side=tk.LEFT, padx=10)

        # Initialize form state based on initial_data or defaults
        self._populate_fields()
        self._on_frequency_change()  # Trigger initial bandwidth setup
        self._apply_readonly_state_to_bw()  # Ensure BW combo is readonly if enabled

        self._center_dialog()

        self.ch_entry.focus_set()  # Set focus to the first editable field
        self.wait_window(self)     # Wait for dialog to close

    def _center_dialog(self):
        """Center the dialog window relative to its parent window."""
        self.update_idletasks()  # Ensure window dimensions are calculated
        dialog_width = self.winfo_reqwidth()
        dialog_height = self.winfo_reqheight()

        self.parent.update_idletasks()
        parent_x = self.parent.winfo_x()
        parent_y = self.parent.winfo_y()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()

        # Calculate centered position
        position_x = parent_x + (parent_width // 2) - (dialog_width // 2)
        position_y = parent_y + (parent_height // 2) - (dialog_height // 2)

        # Ensure dialog stays within screen bounds
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        if position_x + dialog_width > screen_width:
            position_x = screen_width - dialog_width
        if position_x < 0:
            position_x = 0
        if position_y + dialog_height > screen_height:
            position_y = screen_height - dialog_height
        if position_y < 0:
            position_y = 0

        self.geometry(f"+{position_x}+{position_y}")

    def _apply_readonly_state_to_bw(self):
        """
        Ensures the bandwidth combobox is set to 'readonly' if it's currently
        in the 'normal' state (which allows typing). This prevents users from
        entering custom text.
        """
        try:
            # Check if widget exists and is in the 'normal' state
            if hasattr(self, 'bw_combo') and self.bw_combo.winfo_exists():
                current_state = self.bw_combo.cget('state')
                if current_state == tk.NORMAL:
                    self.bw_combo.config(state='readonly')
        except tk.TclError:
            # Ignore errors if widget is destroyed during check
            pass

    def _get_band_from_freq(self, freq_khz):
        """
        Determine the radio band (AM/FM) based on frequency in kHz,
        using the radio's configured ranges.

        Args:
            freq_khz (int): Frequency in kilohertz.

        Returns:
            str: "AM", "FM", or "Unknown".
        """
        if freq_khz is None or freq_khz <= 0:
            return "Unknown"
        # Use the radio instance's configuration if available
        if self.radio and self.radio.config:
            am_range = self.radio.config.get('am_range_khz')
            fm_range = self.radio.config.get('fm_range_khz')
            if am_range and am_range[0] <= freq_khz <= am_range[1]:
                return "AM"
            elif fm_range and fm_range[0] <= freq_khz <= fm_range[1]:
                return "FM"
        # Fallback if config is missing or frequency is outside known ranges
        return "Unknown"

    def _on_frequency_change(self, *args):
        """
        Callback function triggered when the frequency entry changes.
        Updates the available bandwidth options based on the detected band.
        """
        freq_input = self.freq_var.get().strip().lower()
        enable_bw = False
        current_bw_text = self.bw_text_var.get()
        bw_values_to_set = self.all_bw_values  # Default to all values
        detected_band = "Unknown"
        freq_khz = None

        # Handle special case: '0' frequency means skip/disable
        if freq_input == '0':
            enable_bw = False
            detected_band = "Unknown"
        else:
            # Try parsing the frequency input (supports kHz, MHz, or plain number)
            try:
                if freq_input.endswith('khz'):
                    freq_khz = int(float(freq_input[:-3].strip()))
                elif freq_input.endswith('mhz'):
                    freq_khz = int(float(freq_input[:-3].strip()) * 1000)
                elif '.' in freq_input:  # Assume MHz if decimal point present
                    freq_khz = int(float(freq_input) * 1000)
                elif freq_input:  # Assume kHz if integer
                    freq_khz = int(freq_input)

                # If parsing successful and frequency is positive
                if freq_khz is not None and freq_khz > 0:
                    # Check if it's the special skip frequency value
                    is_skip_freq = (self.radio and
                                    self.radio.skip_freq_value is not None and
                                    freq_khz == self.radio.skip_freq_value)
                    if not is_skip_freq:
                        enable_bw = True
                        detected_band = self._get_band_from_freq(freq_khz)

                        # Set appropriate bandwidth values for the detected band
                        if detected_band == "AM":
                            bw_values_to_set = self.am_bw_values
                        elif detected_band == "FM":
                            bw_values_to_set = self.fm_bw_values
                        # If band is Unknown, keep all values but still enable

            except ValueError:
                # Invalid frequency format
                enable_bw = False
                detected_band = "Unknown"

        self.current_band = detected_band  # Store detected band for validation

        # Update the bandwidth combobox state and values
        new_state = 'readonly' if enable_bw else tk.DISABLED
        if hasattr(self, 'bw_combo') and self.bw_combo.winfo_exists():
            try:
                current_state = self.bw_combo.cget('state')
                self.bw_combo.config(values=bw_values_to_set)

                # Try to preserve selection or set a sensible default
                auto_text = self.bw_code_to_text_fm.get(0)  # 'Auto' text
                if current_bw_text in bw_values_to_set:
                    self.bw_text_var.set(current_bw_text)  # Keep current
                elif auto_text and auto_text in bw_values_to_set:
                    self.bw_text_var.set(auto_text)  # Default to 'Auto'
                elif bw_values_to_set:
                    self.bw_text_var.set(bw_values_to_set[0])  # First available
                else:
                    self.bw_text_var.set("")  # Clear if no options

                # Update the state (enabled/disabled) if it changed
                if current_state != new_state:
                    self.bw_combo.config(state=new_state)
                    if not enable_bw:
                        self.bw_text_var.set("")  # Clear text if disabled

            except tk.TclError:
                # Ignore errors if widget is destroyed during update
                pass

    def _validate_length(self, proposed_value, max_len_str):
        """
        Validation function for Entry widgets to limit input length.
        Called automatically by Tkinter's validation mechanism.

        Args:
            proposed_value (str): The potential new value of the Entry.
            max_len_str (str): The maximum allowed length (passed as string).

        Returns:
            bool: True if the proposed value is valid, False otherwise.
        """
        try:
            max_len = int(max_len_str)
            if len(proposed_value) <= max_len:
                return True
            else:
                self.bell()  # Audible feedback for invalid input
                return False
        except ValueError:
            # Should not happen if max_len_str is set correctly
            return False

    def _populate_fields(self):
        """Fill the dialog's input fields with initial data if provided."""
        if self.initial_data:
            # Editing an existing channel
            ch_num = self.initial_data.get('channel', '')
            self.ch_var.set(str(ch_num))
            self.ch_entry.config(state='disabled')  # Channel # not editable

            freq_khz = self.initial_data.get('freq_khz')
            # Check if the channel is marked as skipped using radio helper
            is_skip = (self.radio and
                       self.radio.is_channel_skipped(
                           ch_num, channel_data=self.initial_data
                       ))

            # Set frequency field (display '0' for skipped)
            if is_skip:
                self.freq_var.set("0")
            elif freq_khz is not None:
                # Format frequency nicely (MHz for FM range, kHz otherwise)
                if freq_khz >= 10000:  # Heuristic for FM range
                    self.freq_var.set(f"{freq_khz / 1000.0:.3f}MHz")
                else:
                    self.freq_var.set(f"{freq_khz}kHz")
            else:
                self.freq_var.set("")  # Empty if no frequency data

            # Set bandwidth field based on band and code
            bw_code = self.initial_data.get('bandwidth_code')
            bw_text = ""
            if freq_khz is not None and not is_skip:
                initial_band = self._get_band_from_freq(freq_khz)
                if initial_band == "FM":
                    bw_text = self.bw_code_to_text_fm.get(bw_code, "")
                elif initial_band == "AM":
                    bw_text = self.bw_code_to_text_am.get(bw_code, "")
                # If band is Unknown or code not found, bw_text remains ""
            self.bw_text_var.set(bw_text)

            # Set Mono/Stereo field
            self.mono_stereo_var.set(
                "Stereo" if self.initial_data.get('mono_stereo_code', 0) == 1
                else "Mono"
            )
            # Set PI and PS fields (use empty string if None/missing)
            self.pi_var.set(self.initial_data.get('pi', '') or '')
            self.ps_var.set(self.initial_data.get('ps', '') or '')
        else:
            # Creating a new channel entry (or editing failed read)
            self.mono_stereo_var.set("Stereo")  # Default to Stereo
            self.ch_entry.config(state='normal') # Allow entering channel #

    def _validate_and_accept(self):
        """Validate all user inputs and, if valid, store the result."""
        # --- Validate Channel Number ---
        try:
            ch_num = int(self.ch_var.get())
            # Check if channel is within the radio's supported range
            if not self.radio or not hasattr(self.radio, 'max_channels') or \
               not (1 <= ch_num <= self.radio.max_channels):
                max_ch_str = str(self.radio.max_channels) if self.radio and \
                            hasattr(self.radio, 'max_channels') else '?'
                messagebox.showerror(
                    "Validation Error",
                    f"Channel must be between 1 and {max_ch_str}.",
                    parent=self
                )
                return
        except ValueError:
            messagebox.showerror(
                "Validation Error", "Channel must be a number.", parent=self
            )
            return
        except Exception as e:
            # Catch unexpected errors during validation
            messagebox.showerror(
                "Error", f"Could not validate channel: {e}", parent=self
            )
            return

        # --- Validate Frequency and Determine Skip Intent ---
        freq_input = self.freq_var.get().strip().lower()
        freq_khz = None
        is_skip_intent = (freq_input == '0')

        if is_skip_intent:
            # Handle skip request
            if ch_num == 1:
                messagebox.showerror(
                    "Validation Error",
                    "Channel 1 cannot be skipped.",
                    parent=self
                )
                return
            # Use the radio's defined skip frequency value if available
            freq_khz = self.radio.skip_freq_value if self.radio and \
                      self.radio.skip_freq_value is not None else 0
            # Set default values for skipped channels
            bw_code = 0  # Typically 'Auto' or a default for skipped
            mono_stereo = 1  # Typically Stereo default
            pi = ""
            ps = ""
        else:
            # Handle regular frequency input
            try:
                if freq_input.endswith('khz'):
                    freq_khz = int(float(freq_input[:-3].strip()))
                elif freq_input.endswith('mhz'):
                    freq_khz = int(float(freq_input[:-3].strip()) * 1000)
                elif '.' in freq_input:
                    freq_khz = int(float(freq_input) * 1000)
                elif freq_input:
                    freq_khz = int(freq_input)
                else:
                    raise ValueError("Frequency cannot be empty.")
                if freq_khz < 0:
                    raise ValueError("Frequency cannot be negative.")
            except ValueError as e:
                messagebox.showerror(
                    "Validation Error", f"Invalid frequency: {e}", parent=self
                )
                return

            # --- Validate Bandwidth ---
            bw_text = self.bw_text_var.get()
            bw_code = None
            bw_state = self.bw_combo.cget('state')

            if not bw_text and bw_state != tk.DISABLED:
                # Bandwidth should be selected if the combo is enabled
                messagebox.showerror(
                    "Validation Error",
                    "Please select a Bandwidth.",
                    parent=self
                )
                return
            elif bw_text:
                # Convert selected bandwidth text back to its code based on band
                if self.current_band == "FM":
                    bw_code = self.fm_text_to_code.get(bw_text)
                elif self.current_band == "AM":
                    bw_code = self.am_text_to_code.get(bw_text)
                # If band is Unknown, try both (or handle as error)
                else:
                    bw_code = self.fm_text_to_code.get(
                        bw_text, self.am_text_to_code.get(bw_text)
                    )

                if bw_code is None:
                    # This should ideally not happen if _on_frequency_change works
                    messagebox.showerror(
                        "Validation Error",
                        f"Selected bandwidth '{bw_text}' is not valid for the "
                        f"current frequency band ({self.current_band}).",
                        parent=self
                    )
                    return
            else:
                # Bandwidth is disabled (likely invalid freq), use default code
                bw_code = 0

            # --- Validate Mono/Stereo ---
            mono_stereo_str = self.mono_stereo_var.get()
            if mono_stereo_str == "Stereo":
                mono_stereo = 1
            elif mono_stereo_str == "Mono":
                mono_stereo = 0
            else:
                # Should not happen with readonly combobox
                messagebox.showerror(
                    "Validation Error",
                    "Invalid Mono/Stereo selection.",
                    parent=self
                )
                return

            # --- Process PI and PS Text (already length-validated) ---
            pi = self.pi_var.get().strip().upper()  # Standardize PI to uppercase
            ps = self.ps_var.get().strip()
            # Redundant length check, but safe
            if len(pi) > 4: pi = pi[:4]
            if len(ps) > 8: ps = ps[:8]

        # --- Store Validated Data ---
        self.result_data = {
            'channel': ch_num,
            'freq_khz': freq_khz,
            'bandwidth_code': bw_code,
            'mono_stereo_code': mono_stereo,
            'pi': pi,
            'ps': ps
        }
        self.destroy()  # Close the dialog


class RadioApp(tk.Tk):
    """
    Main application window for the TEF Radio Memory Manager.
    Handles the GUI, user interactions, and communication with the radio backend.
    """
    def __init__(self):
        """Initialize the main application window and its components."""
        super().__init__()
        self.title(f"{APP_TITLE} v{APP_VERSION}")

        # --- Set Application Icon using PhotoImage ---
        self.app_icon = None # Initialize attribute to store the image reference
        try:
            icon_path = resource_path(APP_ICON_FILENAME)
            if os.path.exists(icon_path):
                # Create PhotoImage object
                self.app_icon = tk.PhotoImage(file=icon_path)
                # Set icon using iconphoto (True means use as default)
                # Need to keep self.app_icon reference!
                self.iconphoto(True, self.app_icon)
            else:
                print(f"Warning: Application icon not found at '{icon_path}'")
        except tk.TclError as e:
            # Common error if the image format is wrong or file is corrupt
            print(f"Warning: Could not set application icon using PhotoImage: {e}")
            print("Ensure the image format (e.g., PNG, GIF) is supported by Tk.")
        except Exception as e:
            # Catch any other unexpected errors
            print(f"Warning: An unexpected error occurred setting icon: {e}")
        # --- End Icon Setting ---

        self.geometry("900x650")  # Default window size
        self.protocol("WM_DELETE_WINDOW", self._on_closing) # Handle close button

        # Application state variables
        self.radio = None           # Holds the TEF_ESP32_Radio instance
        self.radio_config = None    # Stores the last successfully read config
        self.available_ports = []   # List of detected serial port devices
        self.is_busy = False        # Flag to indicate ongoing operation
        self.progressbar_visible = False # Track progress bar visibility

        # Apply theme and configure styles
        self._configure_theme()

        # Initialize Tkinter variables for UI elements
        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value=str(DEFAULT_BAUD))
        self.connection_status_var = tk.StringVar(value="Disconnected")
        self.status_var = tk.StringVar(
            value="Ready. Select Port/Baud and Connect."
        )

        # Variables for the Radio Information panel labels
        self.model_var = tk.StringVar(value="N/A")
        self.version_var = tk.StringVar(value="N/A")
        self.mem_pos_var = tk.StringVar(value="N/A")
        self.skip_freq_var = tk.StringVar(value="N/A")
        self.am_range_var = tk.StringVar(value="N/A")
        self.fm_range_var = tk.StringVar(value="N/A")

        # Build and layout the UI widgets
        self._create_widgets()
        self._layout_widgets()
        self._update_button_states() # Set initial button enabled/disabled state
        self._refresh_com_ports()    # Scan for ports on startup

    def _configure_theme(self):
        """Configure the application's theme and default fonts."""
        if sv_ttk:
            sv_ttk.set_theme("light") # Or "dark"
            self.style = ttk.Style(self)
            try:
                # Set default font for most widgets
                self.style.configure('.', font=DEFAULT_FONT)
                # Set specific fonts for Treeview and headings
                self.style.configure(
                    "Treeview",
                    font=TREEVIEW_FONT,
                    rowheight=int(DEFAULT_FONT_SIZE * 2.2) # Adjust row height
                )
                self.style.configure("Treeview.Heading", font=HEADING_FONT)
                self.style.configure("TLabelframe.Label", font=HEADING_FONT)
            except tk.TclError as e:
                # Fallback if font setting fails
                print(f"Warning: Could not set default font "
                      f"'{DEFAULT_FONT_FAMILY}'. Using system default. "
                      f"Error: {e}")
        else:
            # Use default Tkinter theme if sv_ttk is not available
            self.style = ttk.Style(self)

    def _create_widgets(self):
        """Create all the GUI widgets used in the application."""
        # Frame for connection controls (Port, Baud, Connect/Disconnect)
        self._create_connection_frame()

        # Frame to hold the Info and Actions panels side-by-side
        self.top_section_frame = ttk.Frame(self, padding=(0, 5))
        self._create_info_frame()    # Panel for displaying radio info
        self._create_actions_frame() # Panel for action buttons

        # Frame for the main channel list (Treeview)
        self._create_channel_frame()

        # Frame for the status bar at the bottom
        self._create_status_frame()

    def _create_connection_frame(self):
        """Create the widgets for the connection settings area."""
        self.conn_frame = ttk.Frame(self, padding="10")

        ttk.Label(self.conn_frame, text="Port:").pack(
            side=tk.LEFT, padx=(0, 5)
        )
        self.port_combo = ttk.Combobox(
            self.conn_frame,
            textvariable=self.port_var,
            width=25,
            state="readonly" # Prevent typing custom ports
        )
        self.port_combo.pack(side=tk.LEFT, padx=(0, 5))

        self.refresh_ports_button = ttk.Button(
            self.conn_frame,
            text="↺", # Refresh symbol
            width=2,
            command=self._refresh_com_ports
        )
        self.refresh_ports_button.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(self.conn_frame, text="Baud:").pack(
            side=tk.LEFT, padx=(0, 5)
        )
        self.baud_combo = ttk.Combobox(
            self.conn_frame,
            textvariable=self.baud_var,
            values=[str(b) for b in BAUD_RATES],
            width=10,
            state="readonly"
        )
        self.baud_combo.pack(side=tk.LEFT, padx=(0, 15))

        self.connect_button = ttk.Button(
            self.conn_frame,
            text="Connect",
            command=self._connect_radio,
            style="Accent.TButton" # Use theme's accent color
        )
        self.connect_button.pack(side=tk.LEFT, padx=5)

        self.disconnect_button = ttk.Button(
            self.conn_frame,
            text="Disconnect",
            command=self._disconnect_radio
        )
        self.disconnect_button.pack(side=tk.LEFT, padx=(5, 15))

        # Label to display connection status (e.g., "Connected to COM3")
        self.connection_status_label = ttk.Label(
            self.conn_frame,
            textvariable=self.connection_status_var,
            anchor=tk.W
        )
        # Fill remaining horizontal space
        self.connection_status_label.pack(
            side=tk.LEFT, padx=0, fill=tk.X, expand=True
        )

    def _create_info_frame(self):
        """Create the widgets for the radio information display panel."""
        self.info_frame = ttk.LabelFrame(
            self.top_section_frame,
            text="Radio Information",
            padding="10"
        )

        info_pady = 4 # Vertical padding between info rows

        # Grid layout for labels and their corresponding values
        ttk.Label(self.info_frame, text="Model ID:").grid(
            row=0, column=0, sticky="w", padx=5, pady=info_pady
        )
        ttk.Label(self.info_frame, textvariable=self.model_var).grid(
            row=0, column=1, sticky="w", padx=5, pady=info_pady
        )

        ttk.Label(self.info_frame, text="Version:").grid(
            row=1, column=0, sticky="w", padx=5, pady=info_pady
        )
        ttk.Label(self.info_frame, textvariable=self.version_var).grid(
            row=1, column=1, sticky="w", padx=5, pady=info_pady
        )

        ttk.Label(self.info_frame, text="Memory Pos:").grid(
            row=2, column=0, sticky="w", padx=5, pady=info_pady
        )
        ttk.Label(self.info_frame, textvariable=self.mem_pos_var).grid(
            row=2, column=1, sticky="w", padx=5, pady=info_pady
        )

        ttk.Label(self.info_frame, text="Skip Freq:").grid(
            row=3, column=0, sticky="w", padx=5, pady=info_pady
        )
        ttk.Label(self.info_frame, textvariable=self.skip_freq_var).grid(
            row=3, column=1, sticky="w", padx=5, pady=info_pady
        )

        ttk.Label(self.info_frame, text="AM Range:").grid(
            row=4, column=0, sticky="w", padx=5, pady=info_pady
        )
        ttk.Label(self.info_frame, textvariable=self.am_range_var).grid(
            row=4, column=1, sticky="w", padx=5, pady=info_pady
        )

        ttk.Label(self.info_frame, text="FM Range:").grid(
            row=5, column=0, sticky="w", padx=5, pady=info_pady
        )
        ttk.Label(self.info_frame, textvariable=self.fm_range_var).grid(
            row=5, column=1, sticky="w", padx=5, pady=info_pady
        )

        # Allow the value column (column 1) to expand horizontally
        self.info_frame.columnconfigure(1, weight=1)

    def _create_actions_frame(self):
        """Create the widgets for the action buttons panel."""
        self.actions_frame = ttk.LabelFrame(
            self.top_section_frame,
            text="Actions",
            padding="10"
        )

        action_btn_width = 20 # Fixed width for action buttons
        action_pady = 5     # Vertical padding between buttons

        # Grid layout for buttons (2 columns)
        # Left column
        self.read_button = ttk.Button(
            self.actions_frame,
            text="Refresh Configuration", # Changed from "Read Config"
            width=action_btn_width,
            command=self._read_config
        )
        self.read_button.grid(
            row=0, column=0, padx=5, pady=action_pady, sticky="ew"
        )

        self.write_button = ttk.Button(
            self.actions_frame,
            text="Edit Channel",
            width=action_btn_width,
            command=self._open_write_dialog
        )
        self.write_button.grid(
            row=1, column=0, padx=5, pady=action_pady, sticky="ew"
        )

        self.skip_button = ttk.Button(
            self.actions_frame,
            text="Skip Selected",
            width=action_btn_width,
            command=self._skip_channel
        )
        self.skip_button.grid(
            row=2, column=0, padx=5, pady=action_pady, sticky="ew"
        )

        # Right column
        self.erase_button = ttk.Button(
            self.actions_frame,
            text="Erase All",
            width=action_btn_width,
            command=self._erase_all
        )
        self.erase_button.grid(
            row=0, column=1, padx=5, pady=action_pady, sticky="ew"
        )

        self.export_button = ttk.Button(
            self.actions_frame,
            text="Export CSV",
            width=action_btn_width,
            command=self._export_csv
        )
        self.export_button.grid(
            row=1, column=1, padx=5, pady=action_pady, sticky="ew"
        )

        self.import_button = ttk.Button(
            self.actions_frame,
            text="Import CSV",
            width=action_btn_width,
            command=self._import_csv
        )
        self.import_button.grid(
            row=2, column=1, padx=5, pady=action_pady, sticky="ew"
        )

        # Make button columns expand equally within the frame
        self.actions_frame.columnconfigure((0, 1), weight=1)

        # Add author/version info label at the bottom of the actions frame
        info_text = f"{APP_AUTHOR} - v{APP_VERSION} ({APP_DATE})"
        self.info_label = ttk.Label(
            self.actions_frame,
            text=info_text,
            anchor="center",
            foreground="gray" # Dimmed text color
        )
        self.info_label.grid(
            row=3, column=0, columnspan=2,
            sticky='ew',
            pady=(10, 5) # Add some space above
        )

    def _create_channel_frame(self):
        """Create the Treeview widget for displaying channel data."""
        self.channel_frame = ttk.LabelFrame(
            self,
            text="Memory Channels",
            padding="10"
        )

        # Define Treeview columns
        columns = ('#', 'freq', 'bw', 'ms', 'pi', 'ps', 'status')
        self.channel_tree = ttk.Treeview(
            self.channel_frame,
            columns=columns,
            show='headings',      # Only show headings, not the tree column
            selectmode='browse'   # Allow selecting only one row at a time
        )

        # Configure column headings (text displayed)
        self.channel_tree.heading('#', text='#', anchor=tk.CENTER)
        self.channel_tree.heading('freq', text='Freq (MHz)', anchor=tk.CENTER)
        self.channel_tree.heading('bw', text='Bandwidth', anchor=tk.CENTER)
        self.channel_tree.heading('ms', text='Mode', anchor=tk.CENTER)
        self.channel_tree.heading('pi', text='PI', anchor=tk.CENTER)
        self.channel_tree.heading('ps', text='PS', anchor=tk.CENTER)
        self.channel_tree.heading('status', text='Status', anchor=tk.CENTER)

        # Configure column properties (width, alignment, stretch behavior)
        self.channel_tree.column(
            '#', width=50, stretch=tk.NO, anchor=tk.CENTER
        )
        self.channel_tree.column(
            'freq', width=110, stretch=tk.YES, anchor=tk.CENTER
        )
        self.channel_tree.column(
            'bw', width=110, stretch=tk.YES, anchor=tk.CENTER
        )
        self.channel_tree.column(
            'ms', width=90, stretch=tk.YES, anchor=tk.CENTER
        )
        self.channel_tree.column(
            'pi', width=80, stretch=tk.YES, anchor=tk.W # Left align PI
        )
        self.channel_tree.column(
            'ps', width=120, stretch=tk.YES, anchor=tk.W # Left align PS
        )
        self.channel_tree.column(
            'status', width=70, stretch=tk.NO, anchor=tk.CENTER
        )

        # Create and link a vertical scrollbar for the Treeview
        self.tree_scrollbar = ttk.Scrollbar(
            self.channel_frame,
            orient=tk.VERTICAL,
            command=self.channel_tree.yview
        )
        self.channel_tree.configure(yscrollcommand=self.tree_scrollbar.set)

        # Bind events for selection changes and double-clicks
        self.channel_tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.channel_tree.bind('<Double-1>', self._on_tree_double_click)

    def _create_status_frame(self):
        """Create the status bar area at the bottom of the window."""
        self.status_frame = ttk.Frame(self, padding=(5, 3))

        # Label to display status messages
        self.status_label = ttk.Label(
            self.status_frame,
            textvariable=self.status_var,
            anchor=tk.W
        )

        # Progress bar (initially hidden)
        self.progressbar = ttk.Progressbar(
            self.status_frame,
            orient=tk.HORIZONTAL,
            length=200,
            mode='determinate' # Can be 'indeterminate' for pulsing
        )

    def _layout_widgets(self):
        """Arrange the created widgets in the main application window."""
        # Pack top-level frames
        self.conn_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(10, 5))
        self.top_section_frame.pack(
            side=tk.TOP, fill=tk.X, padx=10, pady=(0, 5)
        )

        # Pack Info and Actions frames within their container
        self.info_frame.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10)
        )
        self.actions_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 0))

        # Pack the channel list frame (takes remaining space)
        self.channel_frame.pack(
            side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 5)
        )

        # Pack Treeview and its scrollbar within the channel frame
        self.tree_scrollbar.pack(
            side=tk.RIGHT, fill=tk.Y, padx=(0, 5), pady=(0, 5)
        )
        self.channel_tree.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True, pady=(0, 5)
        )

        # Pack the status bar at the bottom
        self.status_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=0, pady=0)
        self.status_label.pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 10)
        )
        # Progress bar is packed/unpacked dynamically by _set_progress

    def _refresh_com_ports(self):
        """Scan for available serial ports and update the Port combobox."""
        self._update_status("Scanning for serial ports...")
        current_selection = self.port_var.get() # Remember current selection

        try:
            ports = serial.tools.list_ports.comports()
            self.available_ports = [] # Store device names (e.g., 'COM3')
            port_display_list = []    # Store display strings (e.g., 'COM3 - ...')

            for port in ports:
                self.available_ports.append(port.device)

                # Clean up common descriptions for better readability
                description = port.description
                if "USB Serial Port" in description:
                    description = "USB Serial Port"
                elif "USB-SERIAL CH340" in description:
                    description = "USB-SERIAL CH340"
                elif "CP210x" in description:
                    description = "CP210x UART Bridge"
                # Add more common descriptions if needed

                # Limit description length
                display_text = f"{port.device} - {description[:40]}"
                port_display_list.append(display_text)

            # Sort ports naturally (e.g., COM1, COM2, COM10) if natsort available
            try:
                import natsort
                # Sort both lists based on the device name using natural sorting
                combined = sorted(
                    zip(self.available_ports, port_display_list),
                    key=lambda x: natsort.natsort_key(x[0])
                )
                self.available_ports = [p[0] for p in combined]
                port_display_list = [p[1] for p in combined]
            except ImportError:
                # Fallback to basic string sorting if natsort is not installed
                combined = sorted(
                    zip(self.available_ports, port_display_list),
                    key=lambda x: x[0]
                )
                self.available_ports = [p[0] for p in combined]
                port_display_list = [p[1] for p in combined]

            # Update the combobox
            if self.available_ports:
                self.port_combo['values'] = port_display_list
                reselected = False

                # Try to restore the previous selection if it still exists
                if current_selection in self.available_ports:
                    try:
                        # Find the index of the previously selected device
                        idx = self.available_ports.index(current_selection)
                        self.port_combo.current(idx)
                        # Ensure port_var holds the device name, not display text
                        self.port_var.set(self.available_ports[idx])
                        reselected = True
                    except ValueError:
                        # Should not happen if current_selection is in list
                        pass

                # If previous selection not found or wasn't set, select the first
                if not reselected:
                    self.port_combo.current(0)
                    self.port_var.set(self.available_ports[0])

                self.port_combo.config(state="readonly")
                self._update_status(
                    f"Found {len(self.available_ports)} ports. "
                    "Select port and connect."
                )
            else:
                # No ports found
                self.port_combo['values'] = []
                self.port_var.set("")
                self.port_combo.config(state="disabled")
                self._update_status("No serial ports found. Check connections.")
                messagebox.showwarning("Ports", "No serial ports detected.")
        except Exception as e:
            # Handle errors during port scanning
            self._update_status(f"Error scanning ports: {e}")
            messagebox.showerror(
                "Port Scan Error", f"Could not scan for serial ports:\n{e}"
            )
            self.port_combo.config(state="disabled")
        finally:
            # Always update button states after refresh attempt
            self._update_button_states()

    def _start_busy(self, indeterminate=True, maximum=100):
        """
        Enter the 'busy' state: disable controls and show progress bar.

        Args:
            indeterminate (bool): True for pulsing progress, False for value-based.
            maximum (int): The maximum value for determinate progress.
        """
        self.is_busy = True
        # Schedule progress bar update on the main GUI thread
        self.after_idle(
            lambda: self._set_progress(
                0 if not indeterminate else None, # Start at 0 or indeterminate
                maximum if not indeterminate else 0
            )
        )
        self._update_button_states() # Disable buttons

    def _stop_busy(self):
        """Exit the 'busy' state: hide progress bar and re-enable controls."""
        self.is_busy = False
        # Schedule hiding the progress bar on the main GUI thread
        self.after_idle(lambda: self._set_progress(None, None))
        self._update_button_states() # Re-enable appropriate buttons

    def _set_progress(self, value, maximum):
        """
        Configure and display or hide the progress bar.

        Args:
            value (int | None): Current progress value. None for indeterminate.
            maximum (int | None): Maximum value. 0 or None for indeterminate.
                                  None also hides the bar.
        """
        if not hasattr(self, 'progressbar'):
            return # Widget might not exist yet or already destroyed

        # Determine if the progress bar should be active/visible
        is_active = (value is not None) or (maximum is not None and maximum <= 0)

        try:
            if is_active:
                # Show progress bar if it's hidden
                if not self.progressbar_visible:
                    self.progressbar.pack(side=tk.RIGHT, padx=(0, 5))
                    self.progressbar_visible = True

                # Configure mode (indeterminate or determinate)
                if maximum is None or maximum <= 0:
                    self.progressbar.config(mode='indeterminate')
                    self.progressbar.start(20) # Start pulsing animation
                else:
                    self.progressbar.stop() # Stop pulsing if active
                    self.progressbar.config(
                        mode='determinate', maximum=maximum, value=value
                    )
            else:
                # Hide progress bar if it's visible
                if self.progressbar_visible:
                    self.progressbar.pack_forget()
                    self.progressbar_visible = False
                self.progressbar.stop() # Ensure pulsing stops
                self.progressbar.config(mode='determinate', value=0) # Reset
        except tk.TclError:
            # Ignore errors if the widget is destroyed during update
            pass

    def _update_button_states(self):
        """
        Update the enabled/disabled state of various controls based on the
        current application state (connected, busy, config loaded, selection).
        """
        # --- Simplification: Disable almost everything when busy ---
        if self.is_busy:
            self.connect_button.config(state=tk.DISABLED)
            self.disconnect_button.config(state=tk.DISABLED)
            self.port_combo.config(state=tk.DISABLED)
            self.refresh_ports_button.config(state=tk.DISABLED)
            self.baud_combo.config(state=tk.DISABLED)
            # Disable all action buttons
            self._set_action_buttons_state_logical(
                read=False, write=False, skip=False,
                erase=False, export=False, import_csv=False
            )
            return

        # --- Determine state when not busy ---
        is_connected = (self.radio and self.radio.serial_conn and
                        self.radio.serial_conn.is_open)
        has_config = (self.radio_config is not None)
        has_ports = bool(self.available_ports)

        # Get details about the current Treeview selection
        item_selected = bool(self.channel_tree.selection())
        selected_ch = None
        selected_status = None
        if item_selected:
            try:
                selection = self.channel_tree.selection()[0]
                item_data = self.channel_tree.item(selection)
                item_values = item_data.get('values')
                if item_values and len(item_values) > 6:
                    selected_ch = int(item_values[0])
                    selected_status = str(item_values[6]).upper()
            except (IndexError, ValueError, TypeError, tk.TclError):
                # Handle potential errors getting selection data
                selected_ch = None
                selected_status = None
                item_selected = False # Treat as no selection if error occurs

        # Determine if the selected channel can be skipped
        can_skip_selected = (item_selected and selected_ch is not None and
                             selected_ch != 1 and # Cannot skip channel 1
                             selected_status != "SKIP") # Cannot skip if already skipped

        # --- Update Connection Controls ---
        self.connect_button.config(
            state=tk.NORMAL if not is_connected and has_ports else tk.DISABLED
        )
        self.disconnect_button.config(
            state=tk.NORMAL if is_connected else tk.DISABLED
        )
        self.port_combo.config(
            state="readonly" if not is_connected and has_ports else tk.DISABLED
        )
        self.refresh_ports_button.config(
            state=tk.NORMAL if not is_connected else tk.DISABLED
        )
        self.baud_combo.config(
            state="readonly" if not is_connected else tk.DISABLED
        )

        # --- Update Action Buttons based on logical conditions ---
        self._set_action_buttons_state_logical(
            read=is_connected, # Can refresh if connected
            write=is_connected and has_config and item_selected, # Edit needs connection, config, and selection
            skip=is_connected and has_config and can_skip_selected, # Skip needs conn, config, valid selection
            erase=is_connected and has_config, # Erase needs conn, config
            export=has_config, # Export only needs loaded config
            import_csv=is_connected and has_config # Import needs conn, config
        )

    def _set_action_buttons_state_logical(self, read, write, skip, erase,
                                          export, import_csv):
        """
        Helper method to set the state of all action buttons based on boolean flags.

        Args:
            read (bool): Enable Refresh Configuration button.
            write (bool): Enable Edit Channel button.
            skip (bool): Enable Skip Selected button.
            erase (bool): Enable Erase All button.
            export (bool): Enable Export CSV button.
            import_csv (bool): Enable Import CSV button.
        """
        if not hasattr(self, 'read_button'):
            return # Widgets might not be fully created yet

        try:
            # Set state based on boolean flags (NORMAL if True, DISABLED if False)
            self.read_button.config(state=tk.NORMAL if read else tk.DISABLED)
            self.write_button.config(state=tk.NORMAL if write else tk.DISABLED)
            self.skip_button.config(state=tk.NORMAL if skip else tk.DISABLED)
            self.erase_button.config(state=tk.NORMAL if erase else tk.DISABLED)
            self.export_button.config(state=tk.NORMAL if export else tk.DISABLED)
            self.import_button.config(
                state=tk.NORMAL if import_csv else tk.DISABLED
            )
        except tk.TclError:
            # Handle case where widgets might be destroyed during update
            pass

    # --- Connection / Disconnection Logic ---
    def _connect_radio(self):
        """Initiates the connection process to the selected serial port."""
        display_text = self.port_combo.get()
        # Extract the actual device name (e.g., "COM3") from the display text
        port = display_text.split(' - ')[0] if ' - ' in display_text else display_text
        baud = self.baud_var.get()

        if not port:
            messagebox.showerror("Error", "No Serial Port selected.")
            return
        try:
            baud_rate = int(baud)
        except ValueError:
            messagebox.showerror("Error", "Invalid Baud Rate.")
            return

        self._update_status(f"Connecting to {port} at {baud_rate} baud...")
        self._start_busy(indeterminate=True) # Show pulsing progress

        # Run the connection attempt in a separate thread to avoid blocking GUI
        thread = threading.Thread(
            target=self._connect_thread_worker,
            args=(port, baud_rate),
            daemon=True # Allow program exit even if thread is running
        )
        thread.start()

    def _connect_thread_worker(self, port, baud_rate):
        """
        Background worker thread for establishing the serial connection.
        This interacts with the TEF_ESP32_Radio backend class.
        """
        # Create a temporary radio instance to attempt connection
        # Pass callbacks for status and progress updates
        temp_radio = TEF_ESP32_Radio(
            port,
            baudrate=baud_rate,
            status_callback=self._update_status,
            progress_callback=self._update_progress # If connect uses progress
        )
        success = temp_radio.connect() # Attempt connection

        # If successful, assign the instance to the main application
        if success:
            self.radio = temp_radio
        else:
            # Ensure self.radio is None if connection failed
            self.radio = None

        # Schedule the UI update back on the main thread
        if self: # Check if the main application window still exists
            self.after_idle(lambda: self._update_ui_post_connect(success))

    def _update_ui_post_connect(self, success):
        """
        Updates the UI after the connection attempt finishes.
        This method is called from the main GUI thread via `after_idle`.

        Args:
            success (bool): True if the connection was successful, False otherwise.
        """
        if success and self.radio:
            # --- Connection Successful ---
            self.connection_status_var.set(f"Connected to {self.radio.port}")
            self._update_status(
                "Connection successful. Reading configuration..."
            )
            # Automatically read the radio's configuration after connecting
            self._read_config()
            # Note: _read_config will call _stop_busy() upon completion/failure
        else:
            # --- Connection Failed ---
            self._stop_busy() # Stop busy state first
            self.connection_status_var.set("Disconnected")
            port_name = self.port_var.get() # Get the port name attempted
            fail_msg = (f"Could not connect to {port_name}." if port_name
                        else "Could not connect (No port selected?).")
            self._update_status(
                "Connection failed. Check port, baud rate, and radio power."
            )
            messagebox.showerror(
                "Connection Failed",
                f"{fail_msg}\nEnsure the radio is powered and not in use "
                f"by another program. Check status bar for details."
            )
            # _update_button_states() is called by _stop_busy()

    def _disconnect_radio(self):
        """Initiates the disconnection process from the radio."""
        if self.is_busy:
            messagebox.showwarning(
                "Busy", "Cannot disconnect during an ongoing operation."
            )
            return
        if self.radio and self.radio.serial_conn and \
           self.radio.serial_conn.is_open:
            self._update_status("Disconnecting...")
            self._start_busy(indeterminate=True)
            # Run disconnection in a background thread
            thread = threading.Thread(
                target=self._disconnect_thread_worker, daemon=True
            )
            thread.start()
        else:
            # Already disconnected or radio instance not set
            self._update_status("Already disconnected.")
            self.connection_status_var.set("Disconnected")
            self._update_button_states() # Ensure buttons reflect disconnected state

    def _disconnect_thread_worker(self):
        """Background worker thread for closing the serial connection."""
        if self.radio:
            try:
                self.radio.disconnect()
            except Exception as e:
                # Log error but proceed with UI cleanup
                # Use thread-safe update for status
                self._update_status(f"Error during disconnect: {e}")
            finally:
                # Ensure radio instance and config are cleared regardless of error
                self.radio = None
                self.radio_config = None
        # Schedule UI update on the main thread
        if self: # Check if app window still exists
            self.after_idle(self._post_disconnect_update)

    def _post_disconnect_update(self):
        """
        Updates the UI after the disconnection process is complete.
        Called from the main GUI thread via `after_idle`.
        """
        self._clear_info_panel()   # Clear radio info display
        self._clear_treeview()     # Clear channel list
        self.connection_status_var.set("Disconnected")
        self._update_status("Disconnected successfully.")
        self._stop_busy() # Re-enables Connect button, etc.

    def _on_closing(self):
        """
        Handles the event when the user clicks the window's close button.
        Ensures clean disconnection if connected.
        """
        if self.is_busy:
            messagebox.showwarning(
                "Busy",
                "Please wait for the current operation to finish before closing."
            )
            return # Prevent closing while busy

        # Attempt to disconnect cleanly if currently connected
        if self.radio and self.radio.serial_conn and \
           self.radio.serial_conn.is_open:
            self._update_status("Disconnecting on close...")
            try:
                # Perform disconnection synchronously here as the app is closing
                # A short timeout might be added to backend if needed, but
                # direct call is usually fine for closing.
                self.radio.disconnect()
            except Exception as e:
                # Log error but don't prevent the window from closing
                print(f"Error during disconnect on closing: {e}")

        # Destroy the main window and exit the application
        self.destroy()

    # --- Configuration Reading Logic ---
    def _read_config(self):
        """Initiates reading the configuration from the connected radio."""
        # Check if we are logically connected
        if not self.radio or not self.radio.serial_conn or \
           not self.radio.serial_conn.is_open:
            # Check if status implies we *should* be connected
            if self.connection_status_var.get() != "Disconnected":
                messagebox.showerror("Error", "Not connected to radio.")
                self._update_status("Read failed: Not connected.")
            return # Do nothing if not connected

        self._update_status("Reading configuration from radio...")
        # Use indeterminate progress as duration can vary
        self._start_busy(indeterminate=True)
        # Run the potentially time-consuming read operation in a background thread
        thread = threading.Thread(
            target=self._read_config_thread_worker, daemon=True
        )
        thread.start()

    def _read_config_thread_worker(self):
        """Background worker thread for reading radio configuration."""
        config = None
        # Ensure radio instance exists before calling its methods
        if self.radio:
            # Call the backend method to read configuration
            # This method should handle communication and parsing
            config = self.radio.read_configuration()
            # read_configuration should return None on failure

        # Schedule UI update on the main thread with the result
        if self: # Check if app window still exists
            self.after_idle(lambda: self._update_ui_post_read(config))

    def _update_ui_post_read(self, config):
        """
        Updates the UI after the configuration read attempt finishes.
        Handles both success and failure scenarios. Called from main thread.

        Args:
            config (dict | None): The configuration dictionary returned by
                                  radio.read_configuration(), or None if failed.
        """
        if config:
            # --- SUCCESS PATH ---
            self.radio_config = config  # Store the latest valid config

            # Update Info Panel display variables using data from config
            raw_model_id = config.get('radio_model_id') # Get value, or None if missing
            if raw_model_id == 0 or raw_model_id == "0":
                display_model_id = "ESP32_TEF6686"
            elif raw_model_id is not None: # If it exists and is not 0
                display_model_id = str(raw_model_id) # Display other values as string
            else: # If the key was missing or value was None
                display_model_id = "N/A"
            self.model_var.set(display_model_id)

            self.version_var.set(config.get('version', 'N/A'))
            self.mem_pos_var.set(str(config.get('memory_positions', 'N/A')))

            skip_freq = config.get('skip_frequency_value', 'N/A')
            self.skip_freq_var.set(
                f"{skip_freq} kHz" if isinstance(skip_freq, int) else str(skip_freq)
            )

            am_r = config.get('am_range_khz', ('N/A', 'N/A'))
            self.am_range_var.set(
                f"{am_r[0]}-{am_r[1]} kHz" if isinstance(am_r, tuple) else 'N/A'
            )

            fm_r = config.get('fm_range_khz', ('N/A', 'N/A'))
            self.fm_range_var.set(
                f"{fm_r[0]}-{fm_r[1]} kHz" if isinstance(fm_r, tuple) else 'N/A'
            )

            # Populate Treeview with channel data from the config
            self._populate_treeview(config)

            # Update status bar
            self._update_status("Configuration read successfully.")

            # Stop busy state *after* successful UI processing
            # This call will re-enable buttons based on the new 'has_config' state
            self._stop_busy()

        else:
            # --- FAILURE PATH ---
            self.radio_config = None  # Ensure config is cleared on failure

            # Clear displays
            self._clear_info_panel()
            self._clear_treeview()

            # Update status bar
            self._update_status(
                "Failed to read configuration. Check connection/radio."
            )

            # Show error message, but only if we weren't already disconnected
            # (Avoid showing error if user disconnected manually during read)
            if self.connection_status_var.get() != "Disconnected":
                messagebox.showerror(
                    "Read Error",
                    "Failed to read configuration from radio.\n"
                    "The radio might be unresponsive, connection unstable, "
                    "or an unexpected response was received."
                )

            # --- Treat read failure as effective disconnection for UI ---
            # Update connection status label for clarity
            self.connection_status_var.set("Read Failed")

            # Mark the logical connection as broken. This is crucial for
            # _update_button_states (called by _stop_busy) to correctly
            # disable action buttons and re-enable the Connect button.
            if self.radio:
                # Attempt to close the underlying serial port gracefully,
                # but don't let errors here block the UI update.
                try:
                    if self.radio.serial_conn and self.radio.serial_conn.is_open:
                        self.radio.serial_conn.close()
                except Exception as e:
                    # Log if needed, but otherwise ignore cleanup errors
                    print(f"Ignoring error closing serial port after read failure: {e}")
                finally:
                    # Set radio instance to None regardless of close success/failure
                    self.radio = None

            # Stop busy state after failure processing
            # This will correctly update buttons to a 'disconnected' state
            self._stop_busy()

    def _clear_info_panel(self):
        """Resets the labels in the Radio Information panel to 'N/A'."""
        self.model_var.set("N/A")
        self.version_var.set("N/A")
        self.mem_pos_var.set("N/A")
        self.skip_freq_var.set("N/A")
        self.am_range_var.set("N/A")
        self.fm_range_var.set("N/A")

    def _clear_treeview(self):
        """Removes all items from the channel list Treeview."""
        if hasattr(self, 'channel_tree'):
            try:
                # Delete all children of the root item ''
                for item in self.channel_tree.get_children():
                    self.channel_tree.delete(item)
            except tk.TclError:
                # Ignore if treeview doesn't exist or error during deletion
                pass

    def _get_band_from_freq(self, freq_khz):
        """
        Helper to determine band (AM/FM) based on frequency using the
        currently loaded radio configuration (self.radio_config).

        Args:
            freq_khz (int): Frequency in kilohertz.

        Returns:
            str: "AM", "FM", or "Unknown".
        """
        # Check for invalid or skip frequencies first
        if freq_khz is None or freq_khz <= 0:
            return "Unknown"
        # Check against the radio's defined skip frequency value
        if self.radio and self.radio.skip_freq_value is not None and \
           freq_khz == self.radio.skip_freq_value:
             # Skip frequency doesn't belong to a standard band
             return "Unknown"

        # Use radio config ranges if available and loaded
        if self.radio_config:
            am_range = self.radio_config.get('am_range_khz')
            fm_range = self.radio_config.get('fm_range_khz')
            if am_range and am_range[0] <= freq_khz <= am_range[1]:
                return "AM"
            elif fm_range and fm_range[0] <= freq_khz <= fm_range[1]:
                return "FM"
        # Default if ranges not defined or frequency is outside known ranges
        return "Unknown"

    def _populate_treeview(self, config):
        """
        Fills the Treeview with channel data from the provided configuration.

        Args:
            config (dict): The radio configuration dictionary containing
                           channel data under the 'channels' key.
        """
        self._clear_treeview() # Clear existing entries first
        if not config or 'channels' not in config or \
           not hasattr(self, 'channel_tree'):
            return # Nothing to populate

        first_item_id = None # To select the first row after populating

        try:
            # Sort channels by channel number for consistent display
            sorted_channels = sorted(
                config["channels"], key=lambda x: x.get('channel', float('inf'))
            )

            for i, chan in enumerate(sorted_channels):
                ch_num = chan.get('channel', '?')
                freq_khz = chan.get('freq_khz')
                bw_code = chan.get('bandwidth_code', -1) # Numeric code
                ms_code = chan.get('mono_stereo_code', -1) # Numeric code
                pi_val = chan.get('pi', '') or '' # Ensure empty string, not None
                ps_val = chan.get('ps', '') or '' # Ensure empty string, not None

                # --- Determine Status and Format Frequency ---
                # Use radio helper to check if channel is considered skipped
                is_skipped = self.radio.is_channel_skipped(
                    ch_num, channel_data=chan
                ) if self.radio else False
                status_str = "SKIP" if is_skipped else "OK"

                if freq_khz is None:
                    freq_mhz_str = "N/A"
                elif is_skipped:
                    # Display 0.000 for skipped channels for clarity
                    freq_mhz_str = "0.000"
                else:
                    # Format frequency in MHz with 3 decimal places
                    freq_mhz_str = f"{freq_khz / 1000.0:.3f}"

                # --- Determine Bandwidth String (bw_str) ---
                bw_str = f"Code {bw_code}" # Default fallback if unknown
                if not is_skipped:
                    # Look up text based on band and code for non-skipped channels
                    band = self._get_band_from_freq(freq_khz)
                    if band == "FM":
                        bw_str = FM_BANDWIDTHS.get(bw_code, f"FM Code {bw_code}")
                    elif band == "AM":
                        bw_str = AM_BANDWIDTHS.get(bw_code, f"AM Code {bw_code}")
                    # else: Keep default "Code X" for Unknown band
                elif bw_code == 0:
                    # Special handling for code 0 if it means 'Auto' even when skipped
                    # Use 'Auto' text if available, otherwise 'N/A'
                    bw_str = FM_BANDWIDTHS.get(0, "N/A")

                # --- Format Mode (Mono/Stereo) ---
                mono_stereo_str = "Stereo" if ms_code == 1 else \
                                  "Mono" if ms_code == 0 else "N/A"

                # --- Prepare values tuple for Treeview insertion ---
                values = (
                    ch_num, freq_mhz_str, bw_str, mono_stereo_str,
                    pi_val, ps_val, status_str
                )
                # Assign tags for potential styling (e.g., gray out skipped rows)
                tags = ('skipped',) if is_skipped else ('normal',)

                # Insert row into Treeview
                item_id = self.channel_tree.insert(
                    '', tk.END, values=values, tags=tags
                )
                # Keep track of the first item inserted
                if i == 0:
                    first_item_id = item_id

            # --- Apply Styling based on Tags (Optional) ---
            # Example: Gray out text for skipped rows
            # self.channel_tree.tag_configure('skipped', foreground='gray')
            # self.channel_tree.tag_configure('normal', foreground='') # Default

            # --- Select and focus the first row ---
            if first_item_id:
                self.channel_tree.selection_set(first_item_id)
                self.channel_tree.focus(first_item_id)
                self.channel_tree.see(first_item_id) # Ensure it's visible

        except tk.TclError:
            print("Warning: TclError occurred during treeview population.")
        except Exception as e:
            print(f"Error populating treeview: {e}")
            self._update_status(f"Error displaying channels: {e}")

    # --- Treeview Interaction ---
    def _get_selected_channel_num(self):
        """
        Returns the channel number of the currently selected item in the Treeview.

        Returns:
            int | None: The channel number, or None if no valid selection.
        """
        selection = self.channel_tree.selection()
        if selection:
            try:
                item = self.channel_tree.item(selection[0])
                # Channel number is the first value in the 'values' tuple
                return int(item['values'][0])
            except (IndexError, ValueError, TypeError, tk.TclError):
                # Handle cases where selection is invalid or item data missing
                return None
        return None # No selection

    def _get_selected_channel_data(self):
        """
        Retrieves the full configuration data dictionary for the selected channel
        from the locally stored `self.radio_config`.

        Returns:
            dict | None: The channel data dictionary, or None if no selection
                         or data not found in the stored config.
        """
        ch_num = self._get_selected_channel_num()
        if ch_num and self.radio_config and 'channels' in self.radio_config:
            # Find the matching channel data in the stored config list
            for chan_data in self.radio_config['channels']:
                if chan_data.get('channel') == ch_num:
                    return chan_data # Return the found dictionary
        return None # Channel number not found or config missing

    def _on_tree_select(self, event=None):
        """Callback function executed when the Treeview selection changes."""
        # Update button states (e.g., enable/disable Skip/Edit) if not busy
        if not self.is_busy:
            self._update_button_states()

    def _on_tree_double_click(self, event):
        """Callback function executed when a row in the Treeview is double-clicked."""
        # Identify the row clicked based on the event's y-coordinate
        item_id = self.channel_tree.identify_row(event.y)
        if not item_id:
            return # Clicked outside of any row

        # Ensure we are connected and have config before opening edit dialog
        if not self.is_busy and self.radio and self.radio_config:
            # Make sure the double-clicked item is actually selected
            # (identify_row might return item under cursor even if not selected)
            if item_id in self.channel_tree.selection():
                self._open_write_dialog()

    # --- Status Updates ---
    def _update_status(self, message):
        """
        Thread-safe method to update the status bar message label.

        Args:
            message (str): The message to display in the status bar.
        """
        # Use after(0) to schedule the update on the main GUI thread
        # This prevents potential issues if called from a background thread
        if self: # Check if the application window still exists
            try:
                self.after(0, lambda: self.status_var.set(message))
            except tk.TclError:
                # Ignore if the app is closing and widget is destroyed
                pass

    def _update_progress(self, value, maximum):
        """
        Thread-safe method to update the progress bar's value and maximum.

        Args:
            value (int): Current progress value.
            maximum (int): Maximum progress value.
        """
        # Use after(0) to schedule the update on the main GUI thread
        if self: # Check if the application window still exists
            try:
                self.after(0, lambda: self._set_progress(value, maximum))
            except tk.TclError:
                # Ignore if the app is closing and widget is destroyed
                pass

    # --- Channel Actions ---
    def _open_write_dialog(self):
        """Opens the WriteChannelDialog to edit the currently selected channel."""
        if not self.radio or not self.radio_config:
            messagebox.showerror(
                "Error", "Connect and read configuration first."
            )
            return

        # Get the full data dictionary for the selected channel
        selected_data = self._get_selected_channel_data()
        if not selected_data:
             messagebox.showwarning(
                 "Edit Channel", "No channel selected to edit."
             )
             return

        # Open the dialog, passing the current data for the selected channel
        # The dialog will block until closed
        dialog = WriteChannelDialog(self, self.radio, initial_data=selected_data)

        # After the dialog closes, check if it returned validated data
        if dialog.result_data:
            # If user clicked OK and data is valid, execute the write operation
            self._execute_write(dialog.result_data)
        # else: User clicked Cancel or closed the dialog

    def _execute_write(self, channel_data):
        """
        Initiates writing the provided channel data to the radio.
        Runs the actual write operation in a background thread.

        Args:
            channel_data (dict): Dictionary containing the validated channel
                                 details from WriteChannelDialog.
        """
        if not self.radio:
            messagebox.showerror("Error", "Not connected to radio.")
            return

        ch_num = channel_data.get('channel', '?')
        self._update_status(f"Writing Channel {ch_num}...")
        self._start_busy(indeterminate=True) # Show busy indicator

        # Run write operation in background thread
        thread = threading.Thread(
            target=self._write_thread_worker, args=(channel_data,), daemon=True
        )
        thread.start()

    def _write_thread_worker(self, data):
        """Background worker thread for writing a single channel's data."""
        success = False
        messages = ["Write failed: Radio instance not available."] # Default error
        if self.radio:
            try:
                # Call the backend write_channel method with unpacked data
                success, messages = self.radio.write_channel(
                    data['channel'], data['freq_khz'], data['bandwidth_code'],
                    data['mono_stereo_code'], data['pi'], data['ps']
                )
            except Exception as e:
                # Catch potential exceptions during communication
                messages = [f"Write Error: {e}"]
                success = False

        # Schedule UI update on main thread with the result
        if self: # Check if app window exists
            self.after_idle(lambda: self._post_write_refresh(success, messages))

    def _post_write_refresh(self, success, messages):
        """
        Handles UI updates after a channel write attempt finishes.
        Called from main thread via `after_idle`.

        Args:
            success (bool): True if the backend reported success.
            messages (list): List of status/error messages from backend.
        """
        if success:
            self._update_status("Write successful. Refreshing configuration...")
            # Read the configuration again to show the updated data in the UI
            self._read_config()
            # Note: _read_config handles calling _stop_busy() itself
        else:
            # Write failed
            error_details = ", ".join(messages) if messages else "Unknown write error."
            self._update_status(f"Write Failed: {error_details}")
            messagebox.showerror(
                "Write Error", f"Failed to write channel:\n{error_details}"
            )
            # Stop busy state only on failure (success case handled by _read_config)
            self._stop_busy()

    def _skip_channel(self):
        """Initiates skipping the currently selected channel."""
        if not self.radio or not self.radio_config:
            messagebox.showerror("Error", "Connect and read configuration first.")
            return

        ch_num = self._get_selected_channel_num()
        if ch_num is None:
            messagebox.showwarning("Skip Channel", "No channel selected.")
            return

        # Prevent skipping channel 1 (often a special channel)
        if ch_num == 1:
            messagebox.showerror("Error", "Channel 1 cannot be skipped.")
            return

        # Check if already skipped (using treeview data for quick check)
        selection = self.channel_tree.selection()
        if selection:
            try:
                item_data = self.channel_tree.item(selection[0])
                if item_data.get('values') and len(item_data['values']) > 6 and \
                   str(item_data['values'][6]).upper() == "SKIP":
                    messagebox.showinfo(
                        "Skip Channel", f"Channel {ch_num} is already skipped."
                    )
                    return
            except (IndexError, TypeError, tk.TclError):
                 # Error reading treeview data, proceed with confirmation anyway
                 pass

        # Confirm with the user before skipping
        if messagebox.askyesno("Confirm Skip", f"Skip channel {ch_num}?"):
            self._update_status(f"Skipping Channel {ch_num}...")
            self._start_busy(indeterminate=True)
            # Run skip operation in background thread
            thread = threading.Thread(
                target=self._skip_thread_worker, args=(ch_num,), daemon=True
            )
            thread.start()

    def _skip_thread_worker(self, ch_num):
        """Background worker thread for skipping a channel."""
        success = False
        messages = ["Skip failed: Radio instance not available."]
        if self.radio:
            try:
                # Call the backend skip_channel method
                success, messages = self.radio.skip_channel(ch_num)
            except Exception as e:
                messages = [f"Skip Error: {e}"]
                success = False

        # Schedule UI update on main thread
        if self: # Check if app window exists
            self.after_idle(
                lambda: self._post_skip_refresh(success, ch_num, messages)
            )

    def _post_skip_refresh(self, success, ch_num, messages):
        """
        Handles UI updates after a channel skip attempt finishes.
        Called from main thread via `after_idle`.

        Args:
            success (bool): True if the backend reported success.
            ch_num (int): The channel number attempted to skip.
            messages (list): List of status/error messages from backend.
        """
        if success:
            self._update_status(
                f"Channel {ch_num} skip successful. Refreshing configuration..."
            )
            # Refresh data to show the change in the Treeview
            self._read_config()
            # Note: _read_config handles calling _stop_busy()
        else:
            error_details = ", ".join(messages) if messages else "Unknown skip error."
            self._update_status(f"Skip Failed Ch {ch_num}: {error_details}")
            messagebox.showerror(
                "Skip Error",
                f"Failed to skip channel {ch_num}:\n{error_details}"
            )
            # Stop busy state only on failure
            self._stop_busy()

    def _erase_all(self):
        """
        Initiates skipping all channels from 2 up to the maximum.
        Confirms with the user before proceeding.
        """
        if not self.radio or not self.radio_config or \
           not self.radio.max_channels:
            messagebox.showerror(
                "Error", "Connect and read configuration first."
            )
            return

        # Confirmation dialog explaining the action
        msg = (f"This will attempt to set channels 2 through "
               f"{self.radio.max_channels} to the 'SKIP' state.\n"
               f"(Channels already marked as SKIP will be ignored).\n\n"
               f"This operation may take some time.\n\n"
               f"Proceed?")
        if messagebox.askyesno("Confirm Erase All", msg, icon='warning'):
            self._update_status("Starting erase (skip all) process...")
            total_to_check = self.radio.max_channels - 1 # Channels 2 to max
            # Use determinate progress bar for this multi-step operation
            self._start_busy(indeterminate=False, maximum=total_to_check)
            # Run erase operation in background thread
            thread = threading.Thread(
                target=self._erase_all_thread_worker, daemon=True
            )
            thread.start()

    def _erase_all_thread_worker(self):
        """
        Background worker thread to iterate through channels 2 to max
        and attempt to skip each one if not already skipped.
        Updates the progress bar during the operation.
        """
        success_count = 0
        fail_count = 0
        already_skipped_count = 0
        changes_made = False # Track if any actual skip commands were sent

        # Pre-check state again inside the thread
        if not self or not self.radio or not self.radio_config or \
           not self.radio.max_channels:
            # Schedule error handling on main thread if state is invalid
            if self:
                self.after_idle(
                    lambda: self._post_erase_refresh(
                        0, 0, 0, error_msg="Radio/Config became unavailable."
                    )
                )
            return

        max_ch = self.radio.max_channels
        # Create a dictionary for quick lookup of current channel data
        # This avoids repeatedly searching the list inside the loop
        current_channels_dict = {
            c.get('channel'): c for c in self.radio_config.get('channels', [])
            if c.get('channel') is not None
        }

        # Iterate from channel 2 up to the maximum channel number
        for i, ch in enumerate(range(2, max_ch + 1)):
            # Allow breaking the loop if app closes or radio disconnects mid-op
            if not self or not self.radio:
                break # Exit loop if app/connection is gone

            # Update progress bar regardless of skip status
            # Use thread-safe progress update
            self._update_progress(i + 1, max_ch - 1)

            current_data = current_channels_dict.get(ch)
            # Check if the channel is already considered skipped using helper
            if self.radio.is_channel_skipped(ch, channel_data=current_data):
                already_skipped_count += 1
                # Short pause to allow UI updates and prevent flooding radio
                time.sleep(0.01)
                continue # Move to the next channel

            # If not already skipped, attempt to skip it via backend
            changes_made = True # Mark that we are attempting a change
            success, messages = self.radio.skip_channel(ch)

            if success:
                success_count += 1
            else:
                # Log failure, but continue with others
                fail_count += 1
                print(f"Erase All: Failed to skip Ch {ch}: {messages}")

            # Longer pause after a write operation to avoid overwhelming radio
            time.sleep(0.15) # Adjust as needed

        # Schedule final UI update on main thread after loop finishes or breaks
        if self:
            self.after_idle(
                lambda: self._post_erase_refresh(
                    success_count, fail_count, already_skipped_count,
                    changes_made=changes_made # Pass whether changes were attempted
                )
            )

    def _post_erase_refresh(self, successes, failures, already_skipped,
                            error_msg=None, changes_made=False):
        """
        Handles UI updates after the 'erase all' (skip all) operation finishes.
        Called from main thread via `after_idle`.

        Args:
            successes (int): Number of channels successfully skipped.
            failures (int): Number of channels that failed to skip.
            already_skipped (int): Number of channels already skipped.
            error_msg (str, optional): Fatal error message if occurred early.
            changes_made (bool): True if at least one skip command was sent.
        """
        self._stop_busy() # Stop progress bar first

        if error_msg:
            # Handle fatal errors that prevented the operation
            summary = f"Erase Error: {error_msg}"
            messagebox.showerror("Erase Error", summary)
        else:
            # Show summary of results
            summary = (f"Erase All complete. "
                       f"Channels newly skipped: {successes}, "
                       f"Failures: {failures}, Already skipped: {already_skipped}.")
            messagebox.showinfo("Erase Complete", summary)

        self._update_status(summary)

        # Refresh configuration only if the operation ran and attempted changes
        if not error_msg and changes_made:
            self._update_status(f"{summary} Refreshing configuration...")
            self._read_config()
            # _read_config handles its own busy state management

    # --- CSV Operations ---
    def _export_csv(self):
        """Exports the current channel data (from loaded config) to a CSV file."""
        if self.is_busy:
            messagebox.showwarning(
                "Busy", "Please wait for the current operation to finish."
            )
            return
        if not self.radio_config or not self.radio_config.get("channels"):
            messagebox.showwarning(
                "Export Error", "No channel data available to export. "
                                "Please read configuration first."
            )
            return

        # Ask user for the save file location and name
        default_filename = "tef_esp32_channels.csv"
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=default_filename,
            title="Export Channel Data to CSV"
        )
        if not filename:
            self._update_status("Export cancelled by user.")
            return # User cancelled the dialog

        # Start busy state and run the export in a background thread
        self._start_busy(indeterminate=True)
        self._update_status(f"Exporting data to {os.path.basename(filename)}...")
        try:
            export_thread = threading.Thread(
                target=self._export_csv_worker, args=(filename,), daemon=True
            )
            export_thread.start()
        except Exception as e:
            # Handle rare errors starting the thread itself
            self._update_status(f"Failed to start export thread: {e}")
            messagebox.showerror("Export Error", f"Could not start export: {e}")
            self._stop_busy()

    def _export_csv_worker(self, filename):
        """Background worker thread to write channel data to a CSV file."""
        export_count = 0
        error_msg = None
        try:
            # Ensure radio_config and channels exist before proceeding
            if not self.radio_config or "channels" not in self.radio_config:
                raise ValueError("No channel data found in configuration.")

            # Open file for writing with UTF-8 encoding
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                # Write the header row using the imported constant
                writer.writerow(CSV_HEADER)

                # Define the dictionary keys in the exact order of CSV_HEADER
                # These keys must match those used in the channel data dicts
                dict_keys_in_order = [
                    'channel', 'freq_khz', 'bandwidth_code',
                    'mono_stereo_code', 'pi', 'ps'
                ]

                # Sort channels by number before writing
                sorted_channels = sorted(
                    self.radio_config["channels"],
                    key=lambda x: x.get('channel', float('inf'))
                )

                # Write each channel's data as a row
                for chan_data in sorted_channels:
                    row = []
                    for key in dict_keys_in_order:
                        value = chan_data.get(key) # Get value, defaults to None
                        # Convert None to empty string for CSV, keep others (incl 0)
                        row.append('' if value is None else value)

                    writer.writerow(row)
                    export_count += 1

        except ValueError as e: # Catch specific error from check above
             error_msg = str(e)
        except IOError as e:
            error_msg = f"File Write Error: {e}"
        except Exception as e:
            error_msg = f"Unexpected Export Error: {e}"
            print(f"CSV Export Error Traceback: {e}") # Log unexpected errors

        # Schedule UI update on main thread with results
        if self: # Check if app exists
            self.after_idle(
                lambda: self._post_export_update(export_count, error_msg, filename)
            )

    def _post_export_update(self, count, error_msg, filename):
        """
        Handles UI updates after the CSV export attempt finishes.
        Called from main thread via `after_idle`.

        Args:
            count (int): Number of channels successfully exported.
            error_msg (str | None): Error message if export failed.
            filename (str): The target filename.
        """
        if error_msg:
            self._update_status(f"Export Failed: {error_msg}")
            messagebox.showerror("Export Error", error_msg)
        else:
            self._update_status(
                f"Successfully exported {count} channels to "
                f"{os.path.basename(filename)}."
            )
            messagebox.showinfo(
                "Export Successful",
                f"Exported {count} channels to:\n{filename}"
            )
        self._stop_busy() # Stop busy state regardless of success/failure

    def _import_csv(self):
        """
        Initiates importing channel data from a CSV file.
        Parses the file, validates data, compares with current config,
        asks for confirmation, and then writes changes to the radio.
        """
        if self.is_busy:
            messagebox.showwarning(
                "Busy", "Please wait for the current operation to finish."
            )
            return
        if not self.radio or not self.radio_config:
            messagebox.showerror(
                "Import Error", "Cannot import: Connect and read configuration first."
            )
            return

        # Ask user to select the CSV file to import
        filename = filedialog.askopenfilename(
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Import Channel Data from CSV"
        )
        if not filename:
            self._update_status("Import cancelled by user.")
            return # User cancelled the dialog

        # Start busy state (indeterminate initially for parsing phase)
        self._update_status(f"Parsing CSV file: {os.path.basename(filename)}...")
        self._start_busy(indeterminate=True)
        # Run parsing and validation in a background thread
        thread = threading.Thread(
            target=self._import_csv_thread_worker, args=(filename,), daemon=True
        )
        thread.start()

    def _import_csv_thread_worker(self, filename):
        """
        Background worker thread to:
        1. Parse the selected CSV file.
        2. Validate data types and ranges for each row.
        3. Compare imported data with the current `self.radio_config`.
        4. Identify channels that need to be written to the radio.
        """
        imported_channels = {}  # Dict: {ch_num: data_dict} for valid rows
        parse_errors = []       # List for fatal errors stopping the import
        parse_warnings = []     # List for non-fatal issues (skips, truncations)

        try:
            # Open file with 'utf-8-sig' to handle potential Byte Order Mark (BOM)
            with open(filename, 'r', newline='', encoding='utf-8-sig') as csvfile:
                reader = csv.reader(csvfile)

                # --- Read and Validate Header ---
                try:
                    header = next(reader)
                except StopIteration:
                    raise ValueError("CSV file is empty.") # Handle empty file
                # Basic header validation against the expected format
                if header != CSV_HEADER:
                    raise ValueError(
                        f"Invalid CSV header. Expected: {CSV_HEADER}, Found: {header}"
                    )

                # --- Process Data Rows ---
                line_num = 1 # Start counting lines after header
                for row in reader:
                    line_num += 1
                    # Skip completely empty rows
                    if not any(field.strip() for field in row):
                        continue
                    # Check for correct number of columns
                    if len(row) != len(CSV_HEADER):
                        parse_warnings.append(
                            f"Row {line_num}: Skipped (Expected {len(CSV_HEADER)} "
                            f"columns, found {len(row)})."
                        )
                        continue

                    # --- Parse, Validate, and Sanitize Row Data ---
                    try:
                        # Strip whitespace and convert types carefully
                        ch_str = row[0].strip()
                        freq_str = row[1].strip()
                        bw_str = row[2].strip()
                        ms_str = row[3].strip()
                        pi = row[4].strip().upper() # Standardize PI to uppercase
                        ps = row[5].strip()

                        # Convert numeric fields, catching errors
                        ch = int(ch_str)
                        freq = int(freq_str)
                        bw = int(bw_str)
                        ms = int(ms_str)

                        # --- Value Range and Logic Validations ---
                        if not (1 <= ch <= self.radio.max_channels):
                            parse_warnings.append(
                                f"Row {line_num}: Skipped (Channel {ch} out of "
                                f"valid range 1-{self.radio.max_channels})."
                            )
                            continue
                        # Allow 0 frequency for skips, but disallow negative
                        if freq < 0:
                            parse_warnings.append(
                                f"Row {line_num}: Skipped (Frequency {freq} "
                                f"cannot be negative)."
                            )
                            continue
                        # Basic check for bandwidth code (more specific checks later?)
                        if bw < 0:
                             parse_warnings.append(
                                 f"Row {line_num}: Skipped (Bandwidth code {bw} "
                                 f"cannot be negative)."
                             )
                             continue
                        # Validate Mono/Stereo code (must be 0 or 1)
                        if ms not in [0, 1]:
                            parse_warnings.append(
                                f"Row {line_num}: Skipped (Invalid Mono/Stereo "
                                f"code {ms}, must be 0 or 1)."
                            )
                            continue

                        # Truncate PI/PS if too long, issue warning
                        if len(pi) > 4:
                            original_pi = pi
                            pi = pi[:4]
                            parse_warnings.append(
                                f"Row {line_num}: PI '{original_pi}' truncated "
                                f"to '{pi}' (max 4 chars)."
                            )
                        if len(ps) > 8:
                            original_ps = ps
                            ps = ps[:8]
                            parse_warnings.append(
                                f"Row {line_num}: PS '{original_ps}' truncated "
                                f"to '{ps}' (max 8 chars)."
                            )

                        # Prevent skipping channel 1 via CSV import
                        is_skip_freq_csv = (freq == 0) or \
                                           (self.radio.skip_freq_value is not None and
                                            freq == self.radio.skip_freq_value)
                        if ch == 1 and is_skip_freq_csv:
                            parse_warnings.append(
                                f"Row {line_num}: Skipped (Channel 1 cannot be "
                                f"set to skip frequency {freq} via import)."
                            )
                            continue

                        # --- Store Validated Data ---
                        # Use empty string '' instead of None for PI/PS consistency
                        imported_channels[ch] = {
                            'channel': ch, 'freq_khz': freq,
                            'bandwidth_code': bw, 'mono_stereo_code': ms,
                            'pi': pi, 'ps': ps
                        }
                    except ValueError:
                        # Catch errors during int() conversion
                        parse_warnings.append(
                            f"Row {line_num}: Skipped (Invalid number format "
                            f"in one or more fields: {row[:4]})."
                        )
                        continue
                    except IndexError:
                        # Should be caught by column count check, but as fallback
                        parse_warnings.append(
                            f"Row {line_num}: Skipped (Missing data fields)."
                        )
                        continue

        except ValueError as e:
            # Catch specific ValueErrors raised (e.g., bad header, empty file)
            parse_errors.append(str(e))
        except IOError as e:
            parse_errors.append(f"File Read Error: {e}")
        except UnicodeDecodeError as e:
            parse_errors.append(
                f"File Encoding Error: Could not decode as UTF-8. "
                f"Ensure the file is saved with UTF-8 encoding. ({e})"
            )
        except Exception as e:
            # Catch any other unexpected errors during parsing
            parse_errors.append(f"Unexpected Parsing Error: {e}")
            print(f"CSV Import Parse Error Traceback: {e}")

        # --- Compare Imported Data with Current Config (if no fatal errors) ---
        channels_to_write_data = []
        if not parse_errors and imported_channels:
            # Create dict of current channels for efficient lookup
            current_channels_dict = {
                c.get('channel'): c for c in self.radio_config.get('channels', [])
                if c.get('channel') is not None
            }

            # Iterate through successfully parsed channels from CSV
            for ch_num, imp_data in imported_channels.items():
                curr_data = current_channels_dict.get(ch_num)
                needs_write = False

                # Standardize comparison values (use '' for None/empty strings)
                curr_pi = (curr_data.get('pi') or '') if curr_data else ''
                curr_ps = (curr_data.get('ps') or '') if curr_data else ''
                imp_pi = imp_data.get('pi', '') # Already sanitized to ''
                imp_ps = imp_data.get('ps', '') # Already sanitized to ''

                if curr_data is None:
                    # Channel exists in CSV but not currently on radio (or read failed)
                    # Mark for writing only if it's not intended to be skipped
                    is_skip_in_csv = (imp_data['freq_khz'] == 0) or \
                                     (self.radio.skip_freq_value is not None and
                                      imp_data['freq_khz'] == self.radio.skip_freq_value)
                    if not is_skip_in_csv:
                        needs_write = True
                        # Optional: Add warning for channels being added
                        # parse_warnings.append(f"Ch {ch_num}: Will be added.")
                else:
                    # Channel exists on radio, compare relevant fields
                    diffs = []
                    if imp_data['freq_khz'] != curr_data.get('freq_khz'):
                        diffs.append("Freq")
                    if imp_data['bandwidth_code'] != curr_data.get('bandwidth_code'):
                        diffs.append("BW")
                    if imp_data['mono_stereo_code'] != curr_data.get('mono_stereo_code'):
                        diffs.append("Mode")
                    # Case-insensitive compare for PI (already uppercased in imp_data)
                    if imp_pi != curr_pi.upper():
                        diffs.append("PI")
                    # Case-sensitive compare for PS
                    if imp_ps != curr_ps:
                        diffs.append("PS")

                    if diffs:
                        needs_write = True
                        # --- Special Case: Ignore write if only skip freq differs ---
                        # Check if the *only* difference is the representation of
                        # the skip frequency (e.g., 0 vs radio's specific skip value)
                        # AND the channel is already marked as skipped on the radio.
                        is_skip_in_csv = (imp_data['freq_khz'] == 0) or \
                                         (self.radio.skip_freq_value is not None and
                                          imp_data['freq_khz'] == self.radio.skip_freq_value)
                        is_skipped_on_radio = self.radio.is_channel_skipped(
                            ch_num, channel_data=curr_data
                        )

                        # If it's a skip frequency in CSV, and already skipped on radio,
                        # and *all other fields* match, then no write is needed.
                        if is_skip_in_csv and is_skipped_on_radio and \
                           imp_data['bandwidth_code'] == curr_data.get('bandwidth_code') and \
                           imp_data['mono_stereo_code'] == curr_data.get('mono_stereo_code') and \
                           imp_pi == curr_pi.upper() and \
                           imp_ps == curr_ps:
                            needs_write = False # Override: No actual change needed
                            # Optional: Add warning that skip state is unchanged
                            # parse_warnings.append(
                            #    f"Ch {ch_num}: Skip state unchanged, write ignored."
                            # )
                        # else: # Optional: Log which fields differ
                        #     parse_warnings.append(
                        #         f"Ch {ch_num}: Update needed ({','.join(diffs)})."
                        #     )

                # If determined that a write is needed, add data to the list
                if needs_write:
                    channels_to_write_data.append(imp_data)

        # --- Schedule UI Update ---
        # Pass the list of channels to write, errors, and warnings to the main thread
        if self: # Check if app exists
            self.after_idle(
                lambda: self._post_import_parse(
                    channels_to_write_data, parse_errors, parse_warnings
                )
            )

    def _post_import_parse(self, channels_to_write, errors, warnings):
        """
        Handles the results after parsing the CSV file in the background.
        Shows errors or warnings, and if changes are found, asks the user
        for confirmation before proceeding with the write operation.
        Called from the main GUI thread via `after_idle`.

        Args:
            channels_to_write (list): List of channel data dicts needing update.
            errors (list): List of fatal parsing error messages.
            warnings (list): List of non-fatal warning/info messages.
        """
        num_updates = len(channels_to_write)
        num_warnings = len(warnings)
        status_message = "CSV parse finished."

        # --- Handle Fatal Errors ---
        if errors:
            err_msg = "Import failed due to parsing errors:\n\n- " + "\n- ".join(errors)
            self._update_status("Import parse failed. See error message.")
            # Use scrollable message for potentially long error lists
            self._show_scrollable_message("Import Error", err_msg, msg_type="error")
            self._stop_busy() # Stop busy state on fatal error
            return

        # --- Acknowledge Warnings (in status bar and confirmation) ---
        if num_warnings > 0:
            status_message += f" {num_warnings} warnings generated (see console/log)."
            # Optionally log warnings to console for debugging
            print("--- Import Warnings ---")
            for w in warnings:
                print(w)
            print("---------------------")
            # Consider using _show_scrollable_message for warnings too if desired

        # --- Handle No Changes Found ---
        if not channels_to_write:
            self._stop_busy() # Stop busy state as no write is happening
            status_message += " No channel updates required."
            self._update_status(status_message)
            # Show info message to the user
            info_title = "Import Complete"
            info_msg = "No updates needed based on the selected CSV file."
            if num_warnings > 0:
                info_msg += (f"\n\n({num_warnings} warnings were generated during "
                             f"parsing - check console/log for details).")
            messagebox.showinfo(info_title, info_msg, parent=self)
            return

        # --- Prepare Confirmation Dialog for Writing Changes ---
        status_message += f" {num_updates} channel updates identified."
        self._update_status(status_message + " Ready to write.")
        # Stop indeterminate progress bar before showing confirmation
        self._set_progress(None, None)

        # Create the confirmation message text
        confirm_msg = (f"Found {num_updates} channel(s) marked for update "
                       f"based on the CSV file.\n")
        if num_warnings > 0:
             confirm_msg += (f"\n({num_warnings} warnings were generated during "
                             f"parsing - check console/log for details).\n")
        confirm_msg += "\nWrite these changes to the radio?"

        # --- Ask User for Confirmation ---
        if messagebox.askyesno("Confirm Import Write", confirm_msg, parent=self):
            # --- User Confirmed: Start Write Operation ---
            self._update_status(f"Confirmed. Writing {num_updates} channels...")
            # Set determinate progress bar for the write operation
            self._start_busy(indeterminate=False, maximum=num_updates)
            # Run write operation in background thread
            thread = threading.Thread(
                target=self._import_write_thread_worker,
                args=(channels_to_write,), daemon=True
            )
            thread.start()
        else:
            # --- User Cancelled ---
            self._update_status("Import write cancelled by user.")
            self._stop_busy() # Stop busy state if cancelled

    def _import_write_thread_worker(self, channels_to_write):
        """
        Background worker thread to write the imported and confirmed channel
        data to the radio, one channel at a time.
        Updates the progress bar during the operation.
        """
        write_success_count = 0
        write_fail_count = 0
        changes_attempted = False # Track if we actually tried to write

        # Pre-check state again inside the thread
        if not self or not self.radio:
            # Schedule error handling on main thread if state is invalid
            if self:
                self.after_idle(
                    lambda: self._post_import_write(
                        0, 0, False,
                        error_msg="Radio became unavailable before writing."
                    )
                )
            return

        # Sort channels by number for potentially more logical writing order
        channels_to_write.sort(key=lambda x: x.get('channel', float('inf')))

        total_writes = len(channels_to_write)
        for i, chan_data in enumerate(channels_to_write):
            # Allow breaking loop if app closes or disconnects mid-operation
            if not self or not self.radio:
                # If connection lost mid-write, count remaining as failures
                write_fail_count += (total_writes - i)
                break # Exit loop

            changes_attempted = True
            ch = chan_data['channel']
            # Update status frequently during long writes
            self._update_status(
                f"Import: Writing Ch {ch} ({i+1}/{total_writes})..."
            )
            # Call backend write function with data from dict
            success, messages = self.radio.write_channel(
                ch, chan_data['freq_khz'], chan_data['bandwidth_code'],
                chan_data['mono_stereo_code'],
                chan_data.get('pi', ''), chan_data.get('ps', '')
            )
            if success:
                write_success_count += 1
            else:
                write_fail_count += 1
                # Log detailed failure messages for debugging
                print(f"Import write fail Ch {ch}: {messages}")

            # Update progress bar (thread-safe)
            self._update_progress(i + 1, total_writes)
            # Pause briefly between writes to avoid overwhelming the radio
            time.sleep(0.15) # Adjust timing as needed

        # Schedule final UI update on main thread after loop finishes/breaks
        if self:
            self.after_idle(
                lambda: self._post_import_write(
                    write_success_count, write_fail_count, changes_attempted
                )
            )

    def _post_import_write(self, successes, failures, attempted, error_msg=None):
        """
        Handles UI updates after the import write operation finishes or fails.
        Called from the main GUI thread via `after_idle`.

        Args:
            successes (int): Number of channels successfully written.
            failures (int): Number of channels that failed to write.
            attempted (bool): True if at least one write was attempted.
            error_msg (str, optional): Message if error occurred before writing.
        """
        if error_msg:
            # Handle errors that occurred before writing started
            summary = f"Import Write Error: {error_msg}"
            messagebox.showerror("Import Error", summary)
        else:
            # Show summary of write results
            summary = (f"Import write finished. "
                       f"Successful writes: {successes}, Failures: {failures}.")
            messagebox.showinfo("Import Write Complete", summary)

        self._update_status(summary)

        # Refresh configuration if any changes were actually attempted
        # This ensures the UI reflects the final state on the radio
        if attempted:
            self._update_status(f"{summary} Refreshing configuration...")
            self._read_config()
            # _read_config handles its own busy state management
        else:
            # If no writes were attempted (e.g., errors before loop), stop busy here
            self._stop_busy()

    # --- Utility Methods ---
    def _show_scrollable_message(self, title, message, msg_type="info"):
        """
        Displays a message in a separate Toplevel dialog with a
        scrollable text area. Useful for showing longer messages like
        import warnings or detailed errors.

        Args:
            title (str): The title of the dialog window.
            message (str): The message text to display.
            msg_type (str): Message type ('info', 'warning', 'error')
                            to potentially show a standard icon (theme dependent).
        """
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry("600x400")  # Default size, adjust as needed
        dialog.transient(self)      # Keep dialog on top of parent
        dialog.grab_set()           # Make dialog modal (block interaction)
        dialog.resizable(True, True) # Allow resizing

        main_frame = ttk.Frame(dialog, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        # Allow resizing content
        main_frame.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        # Optional: Show standard message icon based on msg_type
        # Note: Icon availability depends on Tk version and theme
        icon_frame = ttk.Frame(main_frame)
        icon_frame.grid(row=0, column=0, sticky='nw', padx=(0, 10))
        try:
            # Standard Tk icon names: error, info, question, warning
            icon_name = f"::tk::icons::{msg_type}" if msg_type in ['error', 'info', 'warning'] else "::tk::icons::info"
            icon_label = ttk.Label(icon_frame, image=icon_name)
            icon_label.pack()
        except tk.TclError:
            # Ignore if icon doesn't exist or theme doesn't support it
            pass

        # Frame for Text widget and Scrollbar
        text_frame = ttk.Frame(main_frame)
        text_frame.grid(row=0, column=1, sticky='nsew')
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)

        # Scrollable Text widget
        text_widget = tk.Text(
            text_frame, wrap=tk.WORD, height=15, width=70,
            relief=tk.FLAT, borderwidth=0, font=DEFAULT_FONT,
            padx=5, pady=5
        )
        scrollbar = ttk.Scrollbar(
            text_frame, orient=tk.VERTICAL, command=text_widget.yview
        )
        text_widget.configure(yscrollcommand=scrollbar.set)

        scrollbar.grid(row=0, column=1, sticky='ns')
        text_widget.grid(row=0, column=0, sticky='nsew')

        # Insert message and disable editing
        text_widget.insert(tk.END, message)
        text_widget.config(state=tk.DISABLED)

        # OK Button at the bottom
        button_frame = ttk.Frame(main_frame, padding=(0, 10, 0, 0))
        button_frame.grid(row=1, column=0, columnspan=2, sticky='ew')
        # Center the button
        button_frame.columnconfigure(0, weight=1)
        ok_button = ttk.Button(
            button_frame, text="OK", command=dialog.destroy,
            style="Accent.TButton"
        )
        ok_button.grid(row=0, column=0)

        # Center the dialog initially
        self.update_idletasks()
        parent_x = self.winfo_x()
        parent_y = self.winfo_y()
        parent_w = self.winfo_width()
        parent_h = self.winfo_height()
        dialog_w = dialog.winfo_reqwidth()
        dialog_h = dialog.winfo_reqheight()
        pos_x = parent_x + (parent_w // 2) - (dialog_w // 2)
        pos_y = parent_y + (parent_h // 2) - (dialog_h // 2)
        dialog.geometry(f'+{pos_x}+{pos_y}')

        # Set focus to the OK button
        ok_button.focus_set()

        # Wait for the dialog to be closed before returning
        dialog.wait_window()

# --- END RadioApp Class ---


# --- Main Execution ---
if __name__ == "__main__":
    # Create and run the main application instance
    app = RadioApp()
    app.mainloop()