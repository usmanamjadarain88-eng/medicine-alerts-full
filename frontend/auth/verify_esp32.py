import time


def verify_pin_esp32(controller, pin):
    ser = getattr(controller, "ser", None)
    log_fn = getattr(controller, "_log", lambda _: None)
    if not ser or not getattr(ser, "is_open", False):
        return False, "Not connected to ESP32"
    if len(pin) != 4 or not pin.isdigit():
        return False, "PIN must be 4 digits"
    try:
        log_fn("\n=== PIN VERIFICATION STARTED ===")
        log_fn(f"PIN entered: {pin}")
        controller.serial_pause = True
        try:
            ser.reset_input_buffer()
        except Exception:
            pass
        time.sleep(0.1)
        command = f"AUTH_PIN:{pin}\n"
        log_fn(f"Sending command: '{command.strip()}'")
        ser.write(command.encode("utf-8"))
        ser.flush()
        log_fn("Command sent, waiting for response...")
        response = ""
        start_time = time.time()
        timeout = 5.0
        while time.time() - start_time < timeout:
            if ser.in_waiting:
                try:
                    raw = ser.readline()
                    response = raw.decode("utf-8", errors="ignore").strip()
                    log_fn(f"Response received: '{response}'")
                    if response:
                        break
                except Exception:
                    pass
            time.sleep(0.05)
        if not response:
            log_fn("⚠ No response from ESP32")
            log_fn("Sending PING to verify connection...")
            try:
                try:
                    ser.reset_input_buffer()
                except Exception:
                    pass
                ser.write(b"PING\n")
                ser.flush()
                time.sleep(1.5)
                if ser.in_waiting:
                    raw = ser.readline()
                    ping_response = raw.decode("utf-8", errors="ignore").strip()
                    log_fn(f"Ping response: '{ping_response}'")
                    return False, "ESP32 not responding to AUTH"
                log_fn("ESP32 not responding to PING")
                return False, "ESP32 not responding"
            except Exception as ex:
                log_fn(f"Ping failed: {ex}")
                return False, "ESP32 not responding"
        up = response.upper()
        if any(p in up for p in ["AUTH_OK", "OK", "SUCCESS", "PIN_OK"]):
            controller.authenticated = True
            controller.wrong_count = 0
            log_fn("✓ PIN verification SUCCESSFUL")
            return True, "PIN verified"
        if any(p in up for p in ["AUTH_FAIL", "FAIL", "ERROR", "PIN_FAIL"]):
            controller.wrong_count = getattr(controller, "wrong_count", 0) + 1
            log_fn("✗ PIN verification FAILED")
            return False, "Wrong PIN"
        log_fn(f"⚠ Ambiguous/missing response: '{response}'")
        return False, "Invalid response from ESP32"
    except Exception as e:
        log_fn(f"✗ Error in verify_pin_esp32: {e}")
        return False, str(e)[:40]
    finally:
        controller.serial_pause = False
