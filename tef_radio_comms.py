#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Interactive command-line tool to manage memory channels on TEF ESP32 based radios
via a serial connection, adhering to the specified Memory Channel Protocol.
Includes CSV export and differential import functionality to minimize flash writes.
"""

import serial
import time
import sys
import textwrap
import re
import csv
import os
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox, filedialog

# Protocol Constants
FM_BANDWIDTHS = {
    0: "auto", 1: "56kHz", 2: "64kHz", 3: "72kHz", 4: "84kHz", 5: "97kHz",
    6: "114kHz", 7: "133kHz", 8: "151kHz", 9: "168kHz", 10: "184kHz",
    11: "200kHz", 12: "217kHz", 13: "236kHz", 14: "254kHz", 15: "287kHz",
    16: "311kHz"
}
AM_BANDWIDTHS = {
    1: "3kHz", 2: "4kHz", 3: "6kHz", 4: "8kHz"
}
ALL_BANDWIDTHS = {**FM_BANDWIDTHS, **AM_BANDWIDTHS}

S_RETURN_CODES = {
    0: "Frequency out of range",
    1: "Memory channel out of range",
    2: "Bandwidth out of range",
    3: "Mono/auto stereo out of range",
    4: "Memory channel 1 can't be set to skip",
    5: "Incorrect PI code",
    6: "Reserved (X)",
    7: "All ok, channel stored"
}

CSV_HEADER = [
    'Channel', 'Frequency kHz', 'Bandwidth Code',
    'Mono/Stereo Code', 'PI Code', 'PS Text'
]


class TEF_ESP32_Radio:
    """
    Manages serial communication and protocol commands for a TEF ESP32 radio.
    Handles connecting, disconnecting, reading configuration, writing channels,
    and interpreting responses based on the documented protocol.
    """
    def __init__(self, port, baudrate=115200, timeout=2.0, status_callback=None, progress_callback=None):
        """
        Initialize radio connection parameters.

        Args:
            port (str): The serial port name (e.g., 'COM3', '/dev/ttyUSB0').
            baudrate (int): Serial communication speed.
            timeout (float): Read timeout in seconds.
            status_callback (callable): Function to call with status messages for the GUI.
            progress_callback (callable): Function to call with progress updates.
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_conn = None
        self.config = None
        self.max_channels = None
        self.skip_freq_value = None
        self.status_callback = status_callback
        self.progress_callback = progress_callback

    def _update_status(self, message):
        """Helper to safely call the status callback if provided."""
        if self.status_callback:
            try:
                self.status_callback(message)
            except Exception as e:
                print(f"Error in status callback: {e}")

    def _update_progress(self, value, maximum):
        """Helper to safely call the progress callback if provided."""
        if self.progress_callback:
            try:
                self.progress_callback(value, maximum)
            except Exception as e:
                print(f"Error in progress callback: {e}")

    def connect(self):
        """
        Establishes the serial connection.
        
        Returns:
            bool: True if connection successful, False otherwise.
        """
        if self.serial_conn and self.serial_conn.is_open:
            self._update_status("Already connected.")
            return True
        
        try:
            # Clear previous config state on new connection attempt
            self.config = None
            self.max_channels = None
            self.skip_freq_value = None
            
            self._update_status(f"Attempting to connect to {self.port}...")
            self.serial_conn = serial.Serial(
                self.port, self.baudrate, timeout=self.timeout
            )
            
            self._update_status("Waiting for device initialization...")
            time.sleep(2)  # Allow time for device to initialize
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()
            
            self._update_status(f"Connected to {self.port} at {self.baudrate} baud.")
            return True
            
        except serial.SerialException as e:
            self._update_status(f"ERROR connecting to {self.port}: {e}")
            self.serial_conn = None
            return False
        except Exception as e:
            self._update_status(f"ERROR: An unexpected error occurred during connection: {e}")
            self.serial_conn = None
            return False

    def disconnect(self):
        """Closes the serial connection."""
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.close()
                self._update_status("Disconnected.")
            except Exception as e:
                self._update_status(f"Error during disconnect: {e}")
        else:
            self._update_status("Already disconnected or not connected.")
        
        self.serial_conn = None

    def _send_command(self, command):
        """
        Send a command to the radio.
        
        Args:
            command (str): The command to send.
            
        Returns:
            bool: True if command sent successfully, False otherwise.
        """
        if not self.serial_conn or not self.serial_conn.is_open:
            self._update_status("ERROR: Not connected to send command.")
            return False
        
        try:
            if not command.endswith('\n'):
                command += '\n'
            self.serial_conn.write(command.encode('utf-8'))
            time.sleep(0.1)  # Small delay to ensure command is processed
            return True
        except serial.SerialException as e:
            self._update_status(f"ERROR sending command '{command.strip()}': {e}")
            return False
        except Exception as e:
            self._update_status(f"ERROR sending command '{command.strip()}': {e}")
            return False

    def _read_line(self, custom_timeout=None):
        """
        Read a line from the serial connection.
        
        Args:
            custom_timeout (float, optional): Custom timeout for this read.
            
        Returns:
            str or None: The decoded line or None on error/timeout.
        """
        if not self.serial_conn or not self.serial_conn.is_open:
            self._update_status("ERROR: Not connected to read line.")
            return None
        
        original_timeout = self.serial_conn.timeout
        if custom_timeout is not None:
            self.serial_conn.timeout = custom_timeout
        
        line_bytes = None
        try:
            line_bytes = self.serial_conn.readline()
            if not line_bytes:
                return None  # Timeout
            
            line_str = line_bytes.decode('utf-8', errors='replace').strip()
            return line_str
            
        except serial.SerialException as e:
            self._update_status(f"ERROR reading line: {e}")
            return None
        except UnicodeDecodeError as e:
            self._update_status(f"ERROR decoding received data: {e}. Raw: {line_bytes!r}")
            return None
        except Exception as e:
            self._update_status(f"ERROR reading line: {e}")
            return None
        finally:
            if custom_timeout is not None:
                self.serial_conn.timeout = original_timeout

    def interpret_s_response(self, code):
        """
        Interpret the response code from an 'S' command.
        
        Args:
            code (int): The response code.
            
        Returns:
            list: List of message strings explaining the response.
        """
        if not isinstance(code, int):
            return ["Invalid response code type received"]
        
        messages = []
        if code & (1 << 7):
            messages.append(S_RETURN_CODES[7])
        
        for i in range(7):
            if code & (1 << i):
                if i in S_RETURN_CODES:
                    if not (i == 7 and (1 << 7) & code):
                        messages.append(S_RETURN_CODES[i])
                else:
                    messages.append(f"Unknown error bit {i} set.")
        
        if not messages:
            if code == 0:
                messages.append("No status bits set (Code 0)")
            else:
                messages.append(f"Unknown response code: {code} (Binary: {code:08b})")
        
        return messages

    def read_configuration(self):
        """
        Reads the full configuration ('s' command), stores it internally.

        Returns:
            dict or None: The parsed configuration dictionary on success, None on failure.
        """
        if not self._send_command('s'):
            self._update_status("Failed to send configuration read command ('s').")
            return None

        self._update_status("Reading configuration from radio...")
        config_data = {
            "radio_model_id": None, "version": None, "memory_positions": None,
            "skip_frequency_value": None, "fm_offset_khz": None,
            "am_range_khz": None, "fm_range_khz": None, "channels": []
        }
        
        # Reset internal state
        self.config = None
        self.max_channels = None
        self.skip_freq_value = None
        
        lines_read = 0
        expected_channels = None

        while True:
            read_timeout = self.timeout if lines_read == 0 else 0.5
            line = self._read_line(custom_timeout=read_timeout)

            if line is None:  # Timeout or error
                if expected_channels is not None and len(config_data["channels"]) < expected_channels:
                    self._update_status(f"Warning: Read timeout before receiving all expected channels ({len(config_data['channels'])}/{expected_channels}).")
                elif lines_read == 0:
                    self._update_status("ERROR: No response received from radio for 's' command.")
                    return None  # Critical failure
                break  # Exit loop

            lines_read += 1
            
            # Parse different response line types
            if line.startswith('r:'):
                config_data['radio_model_id'] = line[2:].strip()
            elif line.startswith('v:'):
                config_data['version'] = line[2:].strip()
            elif line.startswith('m:'):
                try:
                    val = int(line[2:].strip())
                    config_data['memory_positions'] = val
                    self.max_channels = val
                    expected_channels = val
                except ValueError:
                    self._update_status(f"Warning: Could not parse memory positions: {line}")
            elif line.startswith('s:'):
                try:
                    val = int(line[2:].strip())
                    config_data['skip_frequency_value'] = val
                    self.skip_freq_value = val
                except ValueError:
                    self._update_status(f"Warning: Could not parse skip frequency: {line}")
            elif line.startswith('o:'):
                try:
                    parts = line[2:].strip().split(':')
                    config_data['fm_offset_khz'] = int(parts[0])
                except (ValueError, IndexError):
                    self._update_status(f"Warning: Could not parse FM offset: {line}")
            elif line.startswith('a:'):
                try:
                    parts = line[2:].strip().split(',')
                    config_data['am_range_khz'] = (int(parts[0]), int(parts[1]))
                except (ValueError, IndexError, TypeError):
                    self._update_status(f"Warning: Could not parse AM range: {line}")
            elif line.startswith('f:'):
                try:
                    parts = line[2:].strip().split(',')
                    config_data['fm_range_khz'] = (int(parts[0]), int(parts[1]))
                except (ValueError, IndexError, TypeError):
                    self._update_status(f"Warning: Could not parse FM range: {line}")
            else:  # Channel data
                parts = line.split(',')
                if len(parts) == 6:
                    try:
                        pi_val = parts[4] if parts[4] else None
                        ps_val = parts[5] if parts[5] else None
                        channel_info = {
                            "channel": int(parts[0]),
                            "freq_khz": int(parts[1]),
                            "bandwidth_code": int(parts[2]),
                            "mono_stereo_code": int(parts[3]),
                            "pi": pi_val,
                            "ps": ps_val,
                        }
                        config_data["channels"].append(channel_info)
                        
                        # Update progress during channel read
                        if expected_channels:
                            self._update_progress(len(config_data["channels"]), expected_channels)

                    except (ValueError, IndexError):
                        self._update_status(f"Warning: Could not parse channel data: {line}")
                elif lines_read > 7:  # Avoid warnings on initial lines
                    self._update_status(f"Warning: Ignoring unexpected line: {line}")

            # Check for completion
            if expected_channels is not None and len(config_data["channels"]) >= expected_channels:
                self._read_line(custom_timeout=0.2)  # Final quick read
                break

        # Store and return
        self.config = config_data
        self._update_status(f"Configuration read complete. Found {self.max_channels or '?'} channels.")
        return self.config

    def is_channel_skipped(self, ch_num, channel_data=None):
        """
        Check if a channel is marked as skipped.
        
        Args:
            ch_num (int): Channel number to check.
            channel_data (dict, optional): Channel data if already available.
            
        Returns:
            bool: True if channel is skipped, False otherwise.
        """
        if not self.config or not self.config.get("channels"):
            return False
            
        if channel_data is None:
            channel_data = next((c for c in self.config["channels"] if c.get('channel') == ch_num), None)
            if channel_data is None:
                return False
                
        current_freq_khz = channel_data.get('freq_khz')
        if current_freq_khz is None:
            return False
            
        if self.skip_freq_value is not None:
            return current_freq_khz == self.skip_freq_value
        else:
            return current_freq_khz == 0

    def write_channel(self, ch_num, freq_khz, bandwidth_code, mono_stereo_code, pi="", ps=""):
        """
        Write a channel to the radio.
        
        Args:
            ch_num (int): Channel number.
            freq_khz (int): Frequency in kHz.
            bandwidth_code (int): Bandwidth code.
            mono_stereo_code (int): Mono/stereo code (0 or 1).
            pi (str): PI code (optional).
            ps (str): PS text (optional).
            
        Returns:
            tuple: (success, messages) - success is bool, messages is list of strings.
        """
        # Validation
        if not self.serial_conn or not self.serial_conn.is_open:
            return False, ["ERROR: Not connected."]
            
        if not isinstance(ch_num, int) or ch_num < 1 or (self.max_channels and ch_num > self.max_channels):
            return False, [f"Invalid channel number (1-{self.max_channels or '?'})."]
            
        if not isinstance(freq_khz, int) or freq_khz < 0:
            return False, ["Invalid frequency (must be >= 0 kHz)."]
            
        is_skip_freq = (freq_khz == 0) or (self.skip_freq_value is not None and freq_khz == self.skip_freq_value)
        if ch_num == 1 and is_skip_freq:
            return False, ["ERROR: Channel 1 cannot be set to skip."]
            
        if freq_khz == 0 and self.skip_freq_value is not None and self.skip_freq_value != 0:
            self._update_status(f"Info: Sending frequency 0 for skip, but radio uses {self.skip_freq_value} kHz.")
            
        if not isinstance(bandwidth_code, int) or bandwidth_code < 0:
            return False, ["Invalid bandwidth code."]
            
        if mono_stereo_code not in [0, 1]:
            return False, ["Invalid mono/stereo code (must be 0 or 1)."]
            
        # Prepare Command
        pi_upper = pi.upper()
        if len(pi_upper) > 4:
            pi_upper = pi_upper[:4]
            self._update_status("Warning: PI code truncated.")
            
        if len(ps) > 8:
            ps = ps[:8]
            self._update_status("Warning: PS text truncated.")
            
        command = f"S{ch_num},{freq_khz},{bandwidth_code},{mono_stereo_code},{pi_upper},{ps}"
        
        # Send and Handle Response
        self._update_status(f"Sending: {command}")
        if not self._send_command(command):
            return False, ["Failed to send 'S' command."]
            
        response_line = self._read_line()
        if response_line is None:
            return False, ["No response received after 'S' command."]
            
        if response_line.startswith("S:"):
            try:
                return_code = int(response_line[2:].strip())
                messages = self.interpret_s_response(return_code)
                success = bool(return_code & (1 << 7))
                self._update_status(f"Write Ch {ch_num} Response: {', '.join(messages)}")
                return success, messages
            except ValueError:
                msg = f"Could not parse return code: {response_line}"
                self._update_status(f"ERROR: {msg}")
                return False, [msg]
            except Exception as e:
                msg = f"Unexpected error parsing S response: {e}"
                self._update_status(f"ERROR: {msg}")
                return False, [msg]
        else:
            msg = f"Unexpected response format: {response_line}"
            self._update_status(f"ERROR: {msg}")
            return False, [msg]

    def skip_channel(self, ch_num):
        """
        Mark a channel to be skipped.
        
        Args:
            ch_num (int): Channel number to skip.
            
        Returns:
            tuple: (success, messages) - success is bool, messages is list of strings.
        """
        if ch_num == 1:
            return False, ["Error: Channel 1 cannot be skipped."]
            
        freq_to_send = self.skip_freq_value if self.skip_freq_value is not None else 0
        self._update_status(f"Attempting skip for Ch {ch_num} using freq {freq_to_send}...")
        
        # Use parameters documented for skip (BW=0, Stereo=1)
        success, messages = self.write_channel(ch_num, freq_to_send, 0, 1, pi="", ps="")
        return success, messages

    def __enter__(self):
        """Context manager entry."""
        if self.connect():
            return self  # Return the connected instance
        return None  # Indicate connection failure

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False  # Propagate exceptions