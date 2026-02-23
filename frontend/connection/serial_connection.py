import time
import threading
import serial
import serial.tools.list_ports


def connect_to_port(ctrl):
    port_name = getattr(ctrl, "_connect_port_name", None)
    if not port_name:
        return False
    try:
        ctrl._log(f"Attempting to connect to {port_name}...")
        if ctrl.ser:
            try:
                ctrl.ser.close()
            except Exception:
                pass
            time.sleep(0.5)
        ctrl.ser = serial.Serial(
            port=port_name,
            baudrate=115200,
            timeout=2,
            write_timeout=2,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            dsrdtr=False,
            rtscts=False,
        )
        try:
            ctrl.ser.setDTR(False)
            ctrl.ser.setRTS(False)
            time.sleep(0.1)
            ctrl.ser.setDTR(True)
            time.sleep(0.1)
            ctrl.ser.setDTR(False)
        except Exception:
            pass
        ctrl._log("Waiting for ESP32 to boot after reset...")
        time.sleep(3.0)
        ctrl.ser.reset_input_buffer()
        ctrl.ser.reset_output_buffer()
        test_commands = [b"PING\n", b"HELLO\n", b"AT\n", b"\n"]
        got_response = False
        for i, cmd in enumerate(test_commands, start=1):
            try:
                printable = cmd.decode().strip() if cmd.strip() else "EMPTY"
            except Exception:
                printable = "RAW"
            ctrl._log(f"Trying command {i}: {printable}")
            ctrl.ser.write(cmd)
            ctrl.ser.flush()
            time.sleep(0.8)
            response = ""
            if ctrl.ser.in_waiting:
                try:
                    raw = ctrl.ser.readline()
                    response = raw.decode("utf-8", errors="ignore").strip()
                except Exception:
                    response = "partial"
            if response:
                ctrl._log(f"ESP32 response: '{response}'")
                got_response = True
                break
        if not got_response:
            ctrl._log(f"✗ Could not establish connection to {port_name} (no response to test commands)")
            try:
                ctrl.ser.close()
            except Exception:
                pass
            ctrl.ser = None
            return False
        ctrl.connected = True
        ctrl.connected_changed.emit(True)
        start_serial_thread(ctrl)
        ctrl._log(f"✓ Connection established to {port_name}")
        return True
    except Exception as e:
        ctrl._log(f"Connection error: {e}")
        if ctrl.ser:
            try:
                ctrl.ser.close()
            except Exception:
                pass
            ctrl.ser = None
        ctrl.connected = False
        ctrl.connected_changed.emit(False)
        ctrl.status_message.emit(str(e))
        return False


def disconnect_esp32(ctrl):
    ctrl.running = False
    if ctrl.serial_thread and ctrl.serial_thread.is_alive():
        try:
            import threading as _t
            if _t.current_thread() is not ctrl.serial_thread:
                ctrl.serial_thread.join(timeout=1)
        except Exception:
            pass
    try:
        if ctrl.ser and ctrl.ser.is_open:
            ctrl.ser.close()
    except Exception:
        pass
    ctrl.ser = None
    ctrl.connected = False
    ctrl.authenticated = False
    ctrl.active_led_box = None
    # Clear remembered Bluetooth port so wired reconnect is never blocked by stale state.
    ctrl.last_bt_port = None
    ctrl.connected_changed.emit(False)
    ctrl.authenticated_changed.emit(False)
    ctrl.running = True


def start_serial_thread(ctrl):
    if ctrl.serial_thread and ctrl.serial_thread.is_alive():
        return
    ctrl.running = True
    ctrl.serial_thread = threading.Thread(target=_serial_loop, args=(ctrl,), daemon=True, name="SerialMonitor")
    ctrl.serial_thread.start()


def _serial_loop(ctrl):
    while ctrl.running:
        try:
            if ctrl.serial_pause:
                time.sleep(0.05)
                continue
            if not ctrl.ser or not ctrl.ser.is_open:
                time.sleep(1)
                continue
            if not ctrl.ser.in_waiting:
                time.sleep(0.1)
                continue
            if ctrl.serial_pause:
                time.sleep(0.05)
                continue
            raw = ctrl.ser.readline()
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            if "AUTH_OK" in line and not ctrl.authenticated:
                ctrl.authenticated = True
                ctrl.authenticated_changed.emit(True)
            elif "TEMP1:" in line or "TEMP2:" in line:
                ctrl.temperature_update.emit(line)
        except serial.SerialException:
            if ctrl.running:
                disconnect_esp32(ctrl)
            break
        except Exception:
            pass
        time.sleep(0.1)


def get_available_ports():
    return [p.device for p in serial.tools.list_ports.comports()]


def get_connected_port(ctrl):
    if ctrl.ser and getattr(ctrl.ser, "is_open", True) and ctrl.connected:
        return getattr(ctrl.ser, "port", None)
    return None


def quick_test_port(port_name):
    try:
        test_ser = serial.Serial(
            port=port_name,
            baudrate=115200,
            timeout=1.0,
            write_timeout=1.0,
            dsrdtr=False,
            rtscts=False,
        )
        test_ser.setDTR(False)
        test_ser.setRTS(False)
        time.sleep(1.0)
        test_ser.reset_input_buffer()
        test_ser.write(b"PING\n")
        test_ser.flush()
        time.sleep(0.5)
        response = ""
        if test_ser.in_waiting:
            try:
                response_bytes = test_ser.readline()
                response = response_bytes.decode("utf-8", errors="ignore").strip()
            except Exception:
                response = "partial"
        test_ser.close()
        return True, response or "Port opened successfully"
    except serial.SerialException as e:
        return False, f"Port error: {str(e)[:20]}"
    except Exception as e:
        return False, f"Error: {str(e)[:20]}"


def get_bluetooth_ports():
    result = []
    for p in serial.tools.list_ports.comports():
        desc = (p.description or "").lower()
        # Keep Bluetooth matching strict to avoid classifying normal USB-serial as Bluetooth.
        if "bluetooth" in desc or "bt link" in desc or "rfcomm" in desc:
            result.append(p.device)
    return result


def connect_bluetooth(ctrl):
    bt_ports = get_bluetooth_ports()
    if not bt_ports:
        return False
    for port_name in bt_ports:
        is_active, _ = quick_test_port(port_name)
        if is_active:
            ctrl._connect_port_name = port_name
            if connect_to_port(ctrl):
                ctrl.last_bt_port = port_name
                return True
        time.sleep(0.2)
    ctrl._connect_port_name = bt_ports[0]
    if connect_to_port(ctrl):
        ctrl.last_bt_port = bt_ports[0]
        return True
    return False


def send_led_on(ctrl, box_id):
    if not ctrl.ser or not ctrl.ser.is_open:
        return False
    try:
        command = f"LED_ON:{box_id}\n"
        ctrl.ser.write(command.encode())
        ctrl.ser.flush()
        ctrl.active_led_box = box_id
        return True
    except Exception:
        return False


def send_led_off(ctrl, box_id):
    if not ctrl.ser or not ctrl.ser.is_open:
        return False
    try:
        ctrl.ser.reset_input_buffer()
        command = f"LED_OFF:{box_id}\n"
        ctrl.ser.write(command.encode())
        ctrl.ser.flush()
        time.sleep(0.1)
        return True
    except Exception:
        return False


def send_led_all_off(ctrl):
    if not ctrl.ser or not ctrl.ser.is_open:
        return False
    try:
        ctrl.ser.reset_input_buffer()
        ctrl.ser.write(b"LED_ALL_OFF\n")
        ctrl.ser.flush()
        time.sleep(0.2)
        ctrl.active_led_box = None
        return True
    except Exception:
        return False
