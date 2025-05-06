import usb.core
import usb.util
import configparser
import argparse
import os
import re

class Driver(object):
    def __init__(self):
        self.x9_vendorid = 0x18f8  # vendorid
        self.x9_productid = 0x0fc0  # productid
        self.bmRequestType = 0x21
        self.bRequest = 0x09
        self.wValue = 0x0307
        self.wIndex = 0x0001

        self.conquered = False
        self.device_busy = bool()

        self.profile_states = [1, 1, 1, 1, 1, 1]
        self.current_active_profile = 1
        self.cyclic_colors = {"Yellow": 1, "Blue": 1, "Violet": 1, "Green": 1, "Red": 1, "Cyan": 1, "White": 1}

        self.supported_dpis = [200, 400, 600, 800, 1000, 1200, 1600, 2000, 2400, 3200, 4000, 4800]

    def initPayload(self, instruction_code):
        payload = [0x07]
        payload.append(instruction_code)
        return payload

    def find_device(self):
        print("Trying to find device...")
        self.mouse = usb.core.find(idVendor=self.x9_vendorid, idProduct=self.x9_productid)

    def device_state(self):
        try:
            self.device_busy = self.mouse.is_kernel_driver_active(self.wIndex)
        except usb.core.USBError as exception:
            print(exception.strerror)
            if exception.errno == 13:
                print("Try adding a udev rule for your mouse, follow the guide here https://wiki.archlinux.org/index.php/udev#Accessing_firmware_programmers_and_USB_virtual_comm_devicesrunning. Running as root will probably work too but not recommended")
            return -1
        except AttributeError:
            print("Device not found. Try replugging")
            return -2
        print("Device is ready to be configured")
        return 1

    def conquer(self):
        if self.device_busy and not self.conquered:
            self.mouse.detach_kernel_driver(self.wIndex)
            usb.util.claim_interface(self.mouse, self.wIndex)
            self.conquered = True

    def liberate(self):
        if self.conquered:
            try:
                usb.util.release_interface(self.mouse, self.wIndex)
                self.mouse.attach_kernel_driver(self.wIndex)
                self.conquered = False
            except:
                print("Failed to release device back to kernel")

    def addzerobytes(self, list, number_of_bytes):
        for i in range(number_of_bytes):
            list.append(0x00)

    def create_rgb_lights_config(self, changing_scheme, time_duration):
        payload = self.initPayload(0x13)
        payload.append(self.set_cyclic_colors())

        if changing_scheme == "Fixed":
            payload.append(0x86 - time_duration)
        elif changing_scheme == "Cyclic":
            payload.append(0x96 - time_duration)
        elif changing_scheme == "Static":
            payload.append(0x86)
        elif changing_scheme == "Off":
            payload.append(0x87)

        self.addzerobytes(payload, 4)
        return payload

    def create_scrollwheel_config(self, state):
        payload = self.initPayload(0x11)
        if state == "Volume":
            payload.append(0x01)
        else:
            payload.append(0x00)
        self.addzerobytes(payload, 5)
        return(payload)

    def create_dpi_profile_config(self, DPI, profile_to_modify):
        payload = self.initPayload(0x09)
        payload.append(0x40 - 1 + self.current_active_profile)
        payload.append(self.set_dpi_this_profile(DPI, profile_to_modify))
        payload.append(self.set_active_profiles())

        self.addzerobytes(payload, 3)

        return payload

    def create_color_profile_config(self, profile, red, green, blue):
        payload = self.initPayload(0x14)
        internal_profile = (profile - 1) * 2
        internal_red = int((255 - red) / 16)
        internal_green = int((255 - green) / 16)
        internal_blue = int((255 - blue) / 16)

        byte = internal_profile * 16 + internal_green
        payload.append(byte)
        byte = internal_red * 16 + internal_blue
        payload.append(byte)

        payload.append(self.set_active_profiles())

        self.addzerobytes(payload, 3)

        return payload

    def set_active_profiles(self):
        byte = 0
        for i in range(6):
            byte += self.profile_states[i] * 2**i

        return byte

    def set_dpi_this_profile(self, DPI, profile_to_modify):
        internal_dpi = 0
        best_match_dpi = self.find_closest_dpi(DPI)
        if best_match_dpi >= 200 and best_match_dpi <= 1200:
            internal_dpi = int(best_match_dpi / 200)
        elif best_match_dpi == 1600:
            internal_dpi = 0x7
        elif best_match_dpi == 2000:
            internal_dpi = 0x9
        elif best_match_dpi == 2400:
            internal_dpi = 0xb
        elif best_match_dpi == 3200:
            internal_dpi = 0xd
        elif best_match_dpi == 4000:
            internal_dpi = 0xe
        elif best_match_dpi == 4800:
            internal_dpi = 0xf
        else:
            print("DPI out of supported range (200-4800).")

        internal_profile = profile_to_modify + 7
        byte = (internal_dpi * 16) + internal_profile

        return byte

    def set_cyclic_colors(self):
        colorname = list(self.cyclic_colors.keys())
        colors = 0
        for i in range(len(self.cyclic_colors)):
            colors += self.cyclic_colors[colorname[i]] * (2**i)

        return colors

    def send_payload(self, payload):
        self.mouse.ctrl_transfer(self.bmRequestType, self.bRequest, self.wValue, self.wIndex, payload)

    def find_closest_dpi(self, DPI):
        if DPI in self.supported_dpis:
            return DPI

        difference = 4800
        best_match = int()
        for supported in self.supported_dpis:
            temp_diff = DPI - supported
            if (difference >= (temp_diff if temp_diff > 0 else temp_diff * -1)):
                best_match = supported
                difference = temp_diff
        return best_match

    # -------------- NEW: Apply config from driver.conf --------------
    def apply_config_from_file(self, conf_path="driver.conf"):
        if not os.path.exists(conf_path):
            print(f"Config file '{conf_path}' not found!")
            return

        config = configparser.ConfigParser()
        config.read(conf_path)

        # Active Profile (1-based)
        try:
            self.current_active_profile = int(config["Active_Profile"]["profile"])
        except Exception as e:
            print("Error reading active profile:", e)
            self.current_active_profile = 1

        # DPIs
        try:
            for i in range(6):
                key = f"profile_{i+1}"
                dpi = int(config["Profile_DPIs"].get(key, "1200"))
                # Set DPI for each profile (0-based for function)
                payload = self.create_dpi_profile_config(dpi, i)
                self.send_payload(payload)
        except Exception as e:
            print("Error applying DPIs:", e)

        # Profile States (enable/disable)
        try:
            for i in range(6):
                key = f"profile_{i+1}"
                state = int(config["Profile_States"].get(key, "1"))
                self.profile_states[i] = state
        except Exception as e:
            print("Error applying profile states:", e)

        # Profile Colors
        try:
            for i in range(6):
                key = f"profile_{i+1}"
                colorstr = config["Profile_Colors"].get(key, "rgb(255,255,255)")
                match = re.match(r"rgb\((\d+),(\d+),(\d+)\)", colorstr)
                if match:
                    r, g, b = map(int, match.groups())
                else:
                    r, g, b = 255, 255, 255
                payload = self.create_color_profile_config(i+1, r, g, b)
                self.send_payload(payload)
        except Exception as e:
            print("Error applying profile colors:", e)

        # Color Scheme
        try:
            scheme_type = config["Color_Scheme"].get("type", "Static")
            scheme_duration = int(config["Color_Scheme"].get("duration", "1"))
        except Exception as e:
            print("Error reading color scheme, using defaults:", e)
            scheme_type = "Static"
            scheme_duration = 1

        # Cyclic Colors
        try:
            cyclic_colors_section = config["Cyclic_Colors"]
            # Update internal state for cyclic colors
            for k in self.cyclic_colors.keys():
                val = cyclic_colors_section.get(k.lower(), "1")
                self.cyclic_colors[k] = int(val)
        except Exception as e:
            print("Error applying cyclic colors:", e)

        # Apply RGB lighting mode (scheme_type, scheme_duration)
        payload = self.create_rgb_lights_config(scheme_type, scheme_duration)
        self.send_payload(payload)

        print(f"Config from '{conf_path}' has been sent to mouse (active profile {self.current_active_profile})")

class Driver_API(Driver):
    def __init__():
        super().__init__()

if __name__ == "__main__":
    driver = Driver()
    parser = argparse.ArgumentParser(description="Control your mouse settings from CLI")

    subparsers = parser.add_subparsers(dest="command")

    # --- Find Device ---
    find_parser = subparsers.add_parser("find", help="Find and check device state")

    # --- Set DPI ---
    dpi_parser = subparsers.add_parser("set-dpi", help="Set DPI for a profile")
    dpi_parser.add_argument("dpi", type=int, help="Desired DPI value")
    dpi_parser.add_argument("profile", type=int, help="Profile number (0-5)")

    # --- Set RGB Lighting ---
    rgb_parser = subparsers.add_parser("set-rgb", help="Set RGB lighting mode")
    rgb_parser.add_argument("mode", choices=["Fixed", "Cyclic", "Static", "Off"], help="Lighting mode")
    rgb_parser.add_argument("speed", type=int, nargs="?", default=1, help="Transition speed (1-10)")

    # --- Set Color Profile ---
    color_parser = subparsers.add_parser("set-color", help="Set RGB color for a profile")
    color_parser.add_argument("profile", type=int, help="Profile number (1-6)")
    color_parser.add_argument("red", type=int, help="Red value (0-255)")
    color_parser.add_argument("green", type=int, help="Green value (0-255)")
    color_parser.add_argument("blue", type=int, help="Blue value (0-255)")

    # --- Apply config from file ---
    preset_parser = subparsers.add_parser("preset", help="Apply configuration from driver.conf")
    preset_parser.add_argument("--conf", type=str, default="driver.conf", help="Path to config file (default: driver.conf)")

    args = parser.parse_args()

    driver.find_device()
    if driver.device_state() != 1:
        exit(1)

    driver.conquer()

    if args.command == "find":
        print("Device found and ready!")

    elif args.command == "set-dpi":
        payload = driver.create_dpi_profile_config(args.dpi, args.profile)
        driver.send_payload(payload)
        print(f"DPI for profile {args.profile} set to {args.dpi}.")

    elif args.command == "set-rgb":
        payload = driver.create_rgb_lights_config(args.mode, args.speed)
        driver.send_payload(payload)
        print(f"Lighting mode set to {args.mode} with speed {args.speed}.")

    elif args.command == "set-color":
        payload = driver.create_color_profile_config(args.profile, args.red, args.green, args.blue)
        driver.send_payload(payload)
        print(f"Set profile {args.profile} color to R:{args.red} G:{args.green} B:{args.blue}.")

    elif args.command == "preset":
        driver.apply_config_from_file(args.conf)

    driver.liberate()
