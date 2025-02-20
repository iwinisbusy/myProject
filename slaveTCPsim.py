import tkinter as tk
from tkinter import messagebox, ttk
import tkinter.scrolledtext as scrolledtext
import random
import logging
import time
import threading
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
from pymodbus.server.sync import ModbusTcpServer

# Configure logging
logging.basicConfig()
log = logging.getLogger()
log.setLevel(logging.DEBUG)

# Global variables for server components, thread management, and register references
server_thread = None
update_thread = None
modbus_server = None
stop_event = threading.Event()

# Global register objects and configuration parameters
global_coils = None
global_coils_start = 0
global_coils_count = 0

global_discrete_inputs = None
global_discrete_start = 0
global_discrete_count = 0

global_holding_registers = None
global_holding_start = 0
global_holding_count = 0

global_input_registers = None
global_input_start = 0
global_input_count = 0

# Global variables for incremental mode:
global_increment_offset_holding = 0
global_increment_offset_input = 0
global_increment_base_value = 0

# Dictionaries to store confirmed injections.
injection_holding = {}     # {address: value}
injection_input = {}       # {address: value}
injection_coils = {}       # {address: bool}
injection_discrete = {}    # {address: bool}

# Create the root window.
root = tk.Tk()
root.title("Modbus TCP Server")
root.geometry("1050x800")
root.columnconfigure(0, weight=1)
root.rowconfigure(6, weight=1)

# Create the StringVar for word mode.
# Modes: "random", "incremental", "inject"
word_mode_var = tk.StringVar(root, value="random")

def update_mode_fields(*args):
    mode = word_mode_var.get()
    if mode == "incremental":
        increment_step_entry.config(state="normal")
        increment_start_value_entry.config(state="normal")
    else:
        increment_step_entry.config(state="disabled")
        increment_start_value_entry.config(state="disabled")
    if mode == "inject":
        for widget in (holding_injection_address_entry, holding_injection_value_entry,
                       input_injection_address_entry, input_injection_value_entry,
                       coil_injection_address_entry, discrete_injection_address_entry):
            widget.config(state="normal")
        for rb in coil_injection_radio_buttons:
            rb.config(state="normal")
        for rb in discrete_injection_radio_buttons:
            rb.config(state="normal")
        holding_inject_button.config(state="normal")
        input_inject_button.config(state="normal")
        coil_inject_button.config(state="normal")
        discrete_inject_button.config(state="normal")
    else:
        for widget in (holding_injection_address_entry, holding_injection_value_entry,
                       input_injection_address_entry, input_injection_value_entry,
                       coil_injection_address_entry, discrete_injection_address_entry):
            widget.config(state="disabled")
        for rb in coil_injection_radio_buttons:
            rb.config(state="disabled")
        for rb in discrete_injection_radio_buttons:
            rb.config(state="disabled")
        holding_inject_button.config(state="disabled")
        input_inject_button.config(state="disabled")
        coil_inject_button.config(state="disabled")
        discrete_inject_button.config(state="disabled")
    if mode in ["random", "incremental"]:
        injection_holding.clear()
        injection_input.clear()
        injection_coils.clear()
        injection_discrete.clear()

word_mode_var.trace("w", update_mode_fields)

# Subclass the ModbusTcpServer to allow address reuse.
class ReusableModbusTcpServer(ModbusTcpServer):
    allow_reuse_address = True

def run_modbus_server(num_holding, start_holding,
                      num_coils, start_coils,
                      num_discrete, start_discrete,
                      num_input, start_input,
                      ip, port, update_interval, increment_step, slave_id):
    global modbus_server, update_thread
    global global_holding_registers, global_input_registers
    global global_coils, global_discrete_inputs
    global global_holding_start, global_holding_count
    global global_input_start, global_input_count
    global global_coils_start, global_coils_count
    global global_discrete_start, global_discrete_count
    global global_increment_offset_holding, global_increment_offset_input

    # Create register blocks.
    coils = ModbusSequentialDataBlock(start_coils, [False] * num_coils)
    discrete_inputs = ModbusSequentialDataBlock(start_discrete, [False] * num_discrete)
    input_registers = ModbusSequentialDataBlock(start_input, [0] * num_input)
    holding_registers = ModbusSequentialDataBlock(start_holding, 
                        [random.randint(0, 32767) for _ in range(num_holding)])

    # Store registers globally.
    global_coils = coils
    global_coils_start = start_coils
    global_coils_count = num_coils

    global_discrete_inputs = discrete_inputs
    global_discrete_start = start_discrete
    global_discrete_count = num_discrete

    global_holding_registers = holding_registers
    global_holding_start = start_holding
    global_holding_count = num_holding

    global_input_registers = input_registers
    global_input_start = start_input
    global_input_count = num_input

    # Create a dictionary for slave contexts.
    slave_contexts = {
        slave_id: ModbusSlaveContext(
            co=coils,
            di=discrete_inputs,
            hr=holding_registers,
            ir=input_registers
        )
    }
    server_context = ModbusServerContext(slaves=slave_contexts, single=False)

    def update_registers():
        global global_increment_offset_holding, global_increment_offset_input
        while not stop_event.is_set():
            if word_mode_var.get() == "inject":
                new_coils = [False] * num_coils
                new_discrete = [False] * num_discrete
            else:
                new_coils = [random.choice([True, False]) for _ in range(num_coils)]
                new_discrete = [random.choice([True, False]) for _ in range(num_discrete)]
            if word_mode_var.get() == "incremental":
                new_holding = [global_increment_base_value + global_increment_offset_holding] * num_holding
                new_input = [global_increment_base_value + global_increment_offset_input] * num_input
                global_increment_offset_holding += increment_step
                global_increment_offset_input += increment_step
            elif word_mode_var.get() == "random":
                new_holding = [random.randint(0, 32767) for _ in range(num_holding)]
                new_input = [random.randint(0, 32767) for _ in range(num_input)]
            elif word_mode_var.get() == "inject":
                new_holding = [0] * num_holding
                new_input = [0] * num_input
            else:
                new_holding = [0] * num_holding
                new_input = [0] * num_input

            for addr, val in injection_holding.items():
                if start_holding <= addr < start_holding + num_holding:
                    new_holding[addr - start_holding] = val
            for addr, val in injection_input.items():
                if start_input <= addr < start_input + num_input:
                    new_input[addr - start_input] = val
            for addr, val in injection_coils.items():
                if start_coils <= addr < start_coils + num_coils:
                    new_coils[addr - start_coils] = bool(val)
            for addr, val in injection_discrete.items():
                if start_discrete <= addr < start_discrete + num_discrete:
                    new_discrete[addr - start_discrete] = bool(val)

            coils.setValues(start_coils, new_coils)
            discrete_inputs.setValues(start_discrete, new_discrete)
            holding_registers.setValues(start_holding, new_holding)
            input_registers.setValues(start_input, new_input)

            log.info("Updated registers at %s", time.strftime("%Y-%m-%d %H:%M:%S"))
            time.sleep(update_interval)

    update_thread = threading.Thread(target=update_registers)
    update_thread.daemon = True
    update_thread.start()

    modbus_server = ReusableModbusTcpServer(context=server_context, address=(ip, port))
    try:
        modbus_server.serve_forever()
    except Exception as e:
        log.error("Server error: %s", e)
    finally:
        if modbus_server:
            modbus_server.shutdown()
            modbus_server.server_close()
        stop_event.set()
        update_thread.join()

def update_text_widget(widget, text):
    current_y = widget.yview()[0]
    widget.config(state='normal')
    widget.delete('1.0', tk.END)
    widget.insert(tk.END, text)
    widget.config(state='disabled')
    widget.yview_moveto(current_y)

# Injection confirmation functions.
def confirm_inject_holding():
    try:
        addr = int(holding_injection_address_entry.get())
        val = int(holding_injection_value_entry.get())
    except ValueError:
        messagebox.showerror("Input Error", "Invalid Holding Injection parameters")
        return
    injection_holding[addr] = val
    messagebox.showinfo("Injection Confirmed", f"Holding injection set at address {addr} with value {val}")

def confirm_inject_input():
    try:
        addr = int(input_injection_address_entry.get())
        val = int(input_injection_value_entry.get())
    except ValueError:
        messagebox.showerror("Input Error", "Invalid Input Injection parameters")
        return
    injection_input[addr] = val
    messagebox.showinfo("Injection Confirmed", f"Input injection set at address {addr} with value {val}")

def confirm_inject_coils():
    try:
        addr = int(coil_injection_address_entry.get())
        val = int(coil_injection_value_var.get())
    except ValueError:
        messagebox.showerror("Input Error", "Invalid Coil Injection parameters")
        return
    injection_coils[addr] = val
    messagebox.showinfo("Injection Confirmed", f"Coil injection set at address {addr} with value {bool(val)}")

def confirm_inject_discrete():
    try:
        addr = int(discrete_injection_address_entry.get())
        val = int(discrete_injection_value_var.get())
    except ValueError:
        messagebox.showerror("Input Error", "Invalid Discrete Injection parameters")
        return
    injection_discrete[addr] = val
    messagebox.showinfo("Injection Confirmed", f"Discrete injection set at address {addr} with value {bool(val)}")

def disable_inputs():
    for widget in (holding_count_entry, holding_start_entry,
                   coils_count_entry, coils_start_entry,
                   discrete_count_entry, discrete_start_entry,
                   input_count_entry, input_start_entry,
                   ip_entry, port_entry, interval_entry,
                   increment_step_entry, increment_start_value_entry,
                   random_rb, incremental_rb, inject_rb,
                   slave_id_entry, add_extra_count_cb,
                   holding_injection_address_entry, holding_injection_value_entry,
                   input_injection_address_entry, input_injection_value_entry,
                   coil_injection_address_entry, discrete_injection_address_entry):
        widget.config(state="disabled")
    update_mode_fields()

def enable_inputs():
    for widget in (holding_count_entry, holding_start_entry,
                   coils_count_entry, coils_start_entry,
                   discrete_count_entry, discrete_start_entry,
                   input_count_entry, input_start_entry,
                   ip_entry, port_entry, interval_entry,
                   increment_step_entry, increment_start_value_entry,
                   random_rb, incremental_rb, inject_rb,
                   slave_id_entry, add_extra_count_cb,
                   holding_injection_address_entry, holding_injection_value_entry,
                   input_injection_address_entry, input_injection_value_entry,
                   coil_injection_address_entry, discrete_injection_address_entry):
        widget.config(state="normal")
    update_mode_fields()

def start_server():
    global server_thread, global_increment_offset_holding, global_increment_offset_input, global_increment_base_value
    try:
        num_holding = int(holding_count_entry.get())
        start_holding = int(holding_start_entry.get())
    except ValueError:
        messagebox.showerror("Input Error", "Invalid Holding Registers configuration")
        return
    try:
        num_coils = int(coils_count_entry.get())
        start_coils = int(coils_start_entry.get())
    except ValueError:
        messagebox.showerror("Input Error", "Invalid Coils configuration")
        return
    try:
        num_discrete = int(discrete_count_entry.get())
        start_discrete = int(discrete_start_entry.get())
    except ValueError:
        messagebox.showerror("Input Error", "Invalid Discrete Inputs configuration")
        return
    try:
        num_input = int(input_count_entry.get())
        start_input = int(input_start_entry.get())
    except ValueError:
        messagebox.showerror("Input Error", "Invalid Input Registers configuration")
        return

    # Optionally add one to each count.
    if add_extra_count_var.get() == 1:
        num_holding += 1
        num_coils += 1
        num_discrete += 1
        num_input += 1

    ip = ip_entry.get().strip() or "localhost"
    try:
        port = int(port_entry.get())
    except ValueError:
        messagebox.showerror("Input Error", "Invalid port number")
        return
    try:
        update_interval = float(interval_entry.get())
    except ValueError:
        messagebox.showerror("Input Error", "Invalid update interval")
        return
    try:
        increment_step = int(increment_step_entry.get())
    except ValueError:
        increment_step = 1
    try:
        slave_id = int(slave_id_entry.get())
    except ValueError:
        messagebox.showerror("Input Error", "Invalid Slave ID")
        return

    if word_mode_var.get() == "incremental":
        try:
            global_increment_base_value = int(increment_start_value_entry.get())
        except ValueError:
            global_increment_base_value = 0
        global_increment_offset_holding = 0
        global_increment_offset_input = 0
    else:
        global_increment_offset_holding = 0
        global_increment_offset_input = 0

    stop_event.clear()
    start_button.config(state="disabled")
    stop_button.config(state="normal")
    status_label.config(text="Starting server...")

    server_thread = threading.Thread(
        target=run_modbus_server,
        args=(num_holding, start_holding,
              num_coils, start_coils,
              num_discrete, start_discrete,
              num_input, start_input,
              ip, port, update_interval, increment_step, slave_id)
    )
    server_thread.daemon = True
    server_thread.start()
    status_label.config(text="Modbus server is running...")
    disable_inputs()

def stop_server():
    global modbus_server
    if modbus_server:
        log.info("Stopping Modbus server...")
        modbus_server.shutdown()
        modbus_server.server_close()
        status_label.config(text="Server stopped.")
    else:
        status_label.config(text="No server is running.")
    modbus_server = None
    stop_event.set()
    start_button.config(state="normal")
    stop_button.config(state="disabled")
    enable_inputs()

def update_tab_displays():
    if global_discrete_inputs is not None:
        di_vals = global_discrete_inputs.getValues(global_discrete_start, global_discrete_count)
        di_lines = [f"Address {global_discrete_start + i}: {int(val)}" for i, val in enumerate(di_vals)]
        update_text_widget(discrete_tab_text, "\n".join(di_lines))
    if global_coils is not None:
        coil_vals = global_coils.getValues(global_coils_start, global_coils_count)
        coil_lines = [f"Address {global_coils_start + i}: {int(val)}" for i, val in enumerate(coil_vals)]
        update_text_widget(coils_tab_text, "\n".join(coil_lines))
    if global_holding_registers is not None:
        hr_vals = global_holding_registers.getValues(global_holding_start, global_holding_count)
        hr_lines = [f"Address {global_holding_start + i}: {val}" for i, val in enumerate(hr_vals)]
        update_text_widget(holding_tab_text, "\n".join(hr_lines))
    if global_input_registers is not None:
        ir_vals = global_input_registers.getValues(global_input_start, global_input_count)
        ir_lines = [f"Address {global_input_start + i}: {val}" for i, val in enumerate(ir_vals)]
        update_text_widget(input_tab_text, "\n".join(ir_lines))
    root.after(1000, update_tab_displays)

# ----------------- GUI Layout -----------------

# Top Frame: Register Configuration
reg_config_frame = tk.LabelFrame(root, text="Register Configuration", padx=5, pady=5)
reg_config_frame.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
for i in range(4):
    reg_config_frame.columnconfigure(i, weight=1)

# Holding Registers
tk.Label(reg_config_frame, text="Holding Registers Count:").grid(row=0, column=0, sticky="w")
holding_count_entry = tk.Entry(reg_config_frame, width=10)
holding_count_entry.insert(0, "1")
holding_count_entry.grid(row=0, column=1, sticky="w", padx=5)
tk.Label(reg_config_frame, text="Starting Address:").grid(row=0, column=2, sticky="w")
holding_start_entry = tk.Entry(reg_config_frame, width=10)
holding_start_entry.insert(0, "0")
holding_start_entry.grid(row=0, column=3, sticky="w", padx=5)

# Coils
tk.Label(reg_config_frame, text="Coils Count:").grid(row=1, column=0, sticky="w")
coils_count_entry = tk.Entry(reg_config_frame, width=10)
coils_count_entry.insert(0, "1")
coils_count_entry.grid(row=1, column=1, sticky="w", padx=5)
tk.Label(reg_config_frame, text="Starting Address:").grid(row=1, column=2, sticky="w")
coils_start_entry = tk.Entry(reg_config_frame, width=10)
coils_start_entry.insert(0, "0")
coils_start_entry.grid(row=1, column=3, sticky="w", padx=5)

# Discrete Inputs
tk.Label(reg_config_frame, text="Discrete Inputs Count:").grid(row=2, column=0, sticky="w")
discrete_count_entry = tk.Entry(reg_config_frame, width=10)
discrete_count_entry.insert(0, "1")
discrete_count_entry.grid(row=2, column=1, sticky="w", padx=5)
tk.Label(reg_config_frame, text="Starting Address:").grid(row=2, column=2, sticky="w")
discrete_start_entry = tk.Entry(reg_config_frame, width=10)
discrete_start_entry.insert(0, "0")
discrete_start_entry.grid(row=2, column=3, sticky="w", padx=5)

# Input Registers
tk.Label(reg_config_frame, text="Input Registers Count:").grid(row=3, column=0, sticky="w")
input_count_entry = tk.Entry(reg_config_frame, width=10)
input_count_entry.insert(0, "1")
input_count_entry.grid(row=3, column=1, sticky="w", padx=5)
tk.Label(reg_config_frame, text="Starting Address:").grid(row=3, column=2, sticky="w")
input_start_entry = tk.Entry(reg_config_frame, width=10)
input_start_entry.insert(0, "0")
input_start_entry.grid(row=3, column=3, sticky="w", padx=5)

# Checkbox to add extra count (checked by default).
add_extra_count_var = tk.IntVar(value=1)
add_extra_count_cb = tk.Checkbutton(reg_config_frame, text="Add 1 to each count", variable=add_extra_count_var)
add_extra_count_cb.grid(row=4, column=0, columnspan=2, sticky="w", padx=5, pady=2)

# Server Settings Frame
server_frame = tk.LabelFrame(root, text="Server Settings", padx=5, pady=5)
server_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
for i in range(4):
    server_frame.columnconfigure(i, weight=1)

tk.Label(server_frame, text="IP Address:").grid(row=0, column=0, sticky="w")
ip_entry = tk.Entry(server_frame, width=15)
ip_entry.insert(0, "")
ip_entry.grid(row=0, column=1, sticky="w", padx=5)
tk.Label(server_frame, text="Port:").grid(row=0, column=2, sticky="w")
port_entry = tk.Entry(server_frame, width=10)
port_entry.insert(0, "502")
port_entry.grid(row=0, column=3, sticky="w", padx=5)

tk.Label(server_frame, text="Update Interval (sec):").grid(row=1, column=0, sticky="w")
interval_entry = tk.Entry(server_frame, width=10)
interval_entry.insert(0, "1")
interval_entry.grid(row=1, column=1, sticky="w", padx=5)

tk.Label(server_frame, text="Word Mode:").grid(row=2, column=0, sticky="w")
random_rb = tk.Radiobutton(server_frame, text="Random", variable=word_mode_var, value="random")
random_rb.grid(row=2, column=1, sticky="w")
incremental_rb = tk.Radiobutton(server_frame, text="Incremental", variable=word_mode_var, value="incremental")
incremental_rb.grid(row=2, column=2, sticky="w")
inject_rb = tk.Radiobutton(server_frame, text="Injection", variable=word_mode_var, value="inject")
inject_rb.grid(row=2, column=3, sticky="w")

tk.Label(server_frame, text="Increment Step:").grid(row=3, column=0, sticky="w")
increment_step_entry = tk.Entry(server_frame, width=10)
increment_step_entry.insert(0, "1")
increment_step_entry.grid(row=3, column=1, sticky="w", padx=5)
tk.Label(server_frame, text="Increment Start Value:").grid(row=3, column=2, sticky="w")
increment_start_value_entry = tk.Entry(server_frame, width=10)
increment_start_value_entry.insert(0, "0")
increment_start_value_entry.grid(row=3, column=3, sticky="w", padx=5)

tk.Label(server_frame, text="Slave ID:").grid(row=1, column=2, sticky="w")
slave_id_entry = tk.Entry(server_frame, width=10)
slave_id_entry.insert(0, "1")
slave_id_entry.grid(row=1, column=3, sticky="w", padx=5)

# Injection Settings Frame
inject_frame = tk.LabelFrame(root, text="Injection Settings", padx=5, pady=5)
inject_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
for i in range(6):
    inject_frame.columnconfigure(i, weight=1)

# Holding Injection
tk.Label(inject_frame, text="Holding Injection Addr:").grid(row=0, column=0, sticky="w")
holding_injection_address_entry = tk.Entry(inject_frame, width=10)
holding_injection_address_entry.insert(0, "0")
holding_injection_address_entry.grid(row=0, column=1, sticky="w", padx=5)
tk.Label(inject_frame, text="Value:").grid(row=0, column=2, sticky="w")
holding_injection_value_entry = tk.Entry(inject_frame, width=10)
holding_injection_value_entry.insert(0, "0")
holding_injection_value_entry.grid(row=0, column=3, sticky="w", padx=5)
holding_inject_button = tk.Button(inject_frame, text="Inject Holding", command=confirm_inject_holding)
holding_inject_button.grid(row=0, column=4, padx=5, pady=2)

# Input Injection
tk.Label(inject_frame, text="Input Injection Addr:").grid(row=1, column=0, sticky="w")
input_injection_address_entry = tk.Entry(inject_frame, width=10)
input_injection_address_entry.insert(0, "0")
input_injection_address_entry.grid(row=1, column=1, sticky="w", padx=5)
tk.Label(inject_frame, text="Value:").grid(row=1, column=2, sticky="w")
input_injection_value_entry = tk.Entry(inject_frame, width=10)
input_injection_value_entry.insert(0, "0")
input_injection_value_entry.grid(row=1, column=3, sticky="w", padx=5)
input_inject_button = tk.Button(inject_frame, text="Inject Input", command=confirm_inject_input)
input_inject_button.grid(row=1, column=4, padx=5, pady=2)

# Coil Injection
tk.Label(inject_frame, text="Coil Injection Addr:").grid(row=2, column=0, sticky="w")
coil_injection_address_entry = tk.Entry(inject_frame, width=10)
coil_injection_address_entry.insert(0, "0")
coil_injection_address_entry.grid(row=2, column=1, sticky="w", padx=5)
tk.Label(inject_frame, text="Value:").grid(row=2, column=2, sticky="w")
coil_injection_value_var = tk.StringVar(root, value="0")
coil_rb0 = tk.Radiobutton(inject_frame, text="0", variable=coil_injection_value_var, value="0")
coil_rb1 = tk.Radiobutton(inject_frame, text="1", variable=coil_injection_value_var, value="1")
coil_rb0.grid(row=2, column=3, sticky="w", padx=2)
coil_rb1.grid(row=2, column=4, sticky="w", padx=2)
coil_inject_button = tk.Button(inject_frame, text="Inject Coil", command=confirm_inject_coils)
coil_inject_button.grid(row=2, column=5, padx=5, pady=2)
coil_injection_radio_buttons = [coil_rb0, coil_rb1]

# Discrete Injection
tk.Label(inject_frame, text="Discrete Injection Addr:").grid(row=3, column=0, sticky="w")
discrete_injection_address_entry = tk.Entry(inject_frame, width=10)
discrete_injection_address_entry.insert(0, "0")
discrete_injection_address_entry.grid(row=3, column=1, sticky="w", padx=5)
tk.Label(inject_frame, text="Value:").grid(row=3, column=2, sticky="w")
discrete_injection_value_var = tk.StringVar(root, value="0")
discrete_rb0 = tk.Radiobutton(inject_frame, text="0", variable=discrete_injection_value_var, value="0")
discrete_rb1 = tk.Radiobutton(inject_frame, text="1", variable=discrete_injection_value_var, value="1")
discrete_rb0.grid(row=3, column=3, sticky="w", padx=2)
discrete_rb1.grid(row=3, column=4, sticky="w", padx=2)
discrete_inject_button = tk.Button(inject_frame, text="Inject Discrete", command=confirm_inject_discrete)
discrete_inject_button.grid(row=3, column=5, padx=5, pady=2)
discrete_injection_radio_buttons = [discrete_rb0, discrete_rb1]

# Control Buttons Frame
control_frame = tk.Frame(root)
control_frame.grid(row=3, column=0, padx=10, pady=10, sticky="ew")
start_button = tk.Button(control_frame, text="Start Server", command=start_server, width=15)
start_button.pack(side="left", padx=10)
stop_button = tk.Button(control_frame, text="Stop Server", command=stop_server, width=15)
stop_button.pack(side="left", padx=10)
stop_button.config(state="disabled")

# Status and Note Frame
status_frame = tk.Frame(root)
status_frame.grid(row=4, column=0, padx=10, pady=5, sticky="ew")
status_label = tk.Label(status_frame, text="Server not running", fg="red")
status_label.pack(side="top", pady=5)
note_text = (
    "Note: This software continuously updates Modbus registers.\n"
    "- Boolean registers (Discrete Inputs & Coils) are auto-generated randomly unless in Injection mode.\n"
    "- Word registers (Holding & Input Registers) can be random, incremental, or injected."
)
note_label = tk.Label(status_frame, text=note_text, wraplength=900, justify="center", fg="blue")
note_label.pack(side="top", pady=5)

# Notebook for Register Display
display_notebook = ttk.Notebook(root)
display_notebook.grid(row=5, column=0, padx=10, pady=10, sticky="nsew")
tab_discrete = tk.Frame(display_notebook)
tab_coils = tk.Frame(display_notebook)
tab_holding = tk.Frame(display_notebook)
tab_input = tk.Frame(display_notebook)
display_notebook.add(tab_discrete, text="Discrete Inputs")
display_notebook.add(tab_coils, text="Coils")
display_notebook.add(tab_holding, text="Holding Registers")
display_notebook.add(tab_input, text="Input Registers")

discrete_tab_text = scrolledtext.ScrolledText(tab_discrete, wrap=tk.WORD)
discrete_tab_text.pack(fill="both", expand=True, padx=5, pady=5)
discrete_tab_text.config(state='disabled')
coils_tab_text = scrolledtext.ScrolledText(tab_coils, wrap=tk.WORD)
coils_tab_text.pack(fill="both", expand=True, padx=5, pady=5)
coils_tab_text.config(state='disabled')
holding_tab_text = scrolledtext.ScrolledText(tab_holding, wrap=tk.WORD)
holding_tab_text.pack(fill="both", expand=True, padx=5, pady=5)
holding_tab_text.config(state='disabled')
input_tab_text = scrolledtext.ScrolledText(tab_input, wrap=tk.WORD)
input_tab_text.pack(fill="both", expand=True, padx=5, pady=5)
input_tab_text.config(state='disabled')

# Initialize states and start update loop.
update_mode_fields()
update_tab_displays()

root.mainloop()
