import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
import sqlite3
import random
import csv

DB_NAME = "battery_thermal.db"
TEMP_WARNING = 45.0
TEMP_CRITICAL = 50.0
TARGET_DELTA_T = 5.0

BG = "#eef7ff"
PANEL = "#ffffff"
TEXT = "#26384a"
MUTED = "#6f879d"
ACCENT = "#3188c8"
PALE_BLUE = "#d9edff"
MID_BLUE = "#91cfff"
BORDER = "#d5e5f1"


@dataclass
class SensorReading:
    battery_id: str
    cell_id: str
    temperature: float
    voltage: float
    current: float
    coolant_temperature: float
    flow_rate: float
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self.battery_id.strip() or not self.cell_id.strip():
            raise ValueError("Battery ID and Cell ID are required.")
        for field in (
            "temperature", "voltage", "current",
            "coolant_temperature", "flow_rate"
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field.replace('_', ' ').title()} cannot be negative.")

    def summary(self):
        return (
            f"{self.battery_id}/{self.cell_id} | "
            f"{self.temperature:.1f} °C | {self.voltage:.2f} V | "
            f"{self.current:.2f} A | Coolant "
            f"{self.coolant_temperature:.1f} °C | "
            f"Flow {self.flow_rate:.2f} L/min"
        )


class Sensor(ABC):
    @abstractmethod
    def read_value(self, reading):
        pass


class TemperatureSensor(Sensor):
    def read_value(self, reading):
        return reading.temperature


class CoolantFlowSensor(Sensor):
    def read_value(self, reading):
        return reading.flow_rate


class CoolingFluid(ABC):
    def __init__(self, name, concentration, reynolds, inlet_temp,
                 pressure_drop, heat_transfer, max_temp):
        self.name = name
        self.concentration = concentration
        self.reynolds = reynolds
        self.inlet_temp = inlet_temp
        self.pressure_drop = pressure_drop
        self.heat_transfer = heat_transfer
        self.max_temp = max_temp

    @abstractmethod
    def performance_score(self):
        pass


class WaterCase(CoolingFluid):
    def performance_score(self):
        return (
            self.heat_transfer
            - self.pressure_drop * 0.15
            - self.max_temp * 0.2
        )


class NanofluidCase(CoolingFluid):
    def performance_score(self):
        return (
            self.heat_transfer
            - self.pressure_drop * 0.15
            - self.max_temp * 0.2
            - self.concentration * 0.1
        )


class ThermalAnalysis:
    @staticmethod
    def temperature_difference(hot, cold):
        return abs(hot - cold)

    @staticmethod
    def rank_cases(cases):
        return sorted(cases, key=lambda case: case["score"], reverse=True)


class ThermalDatabase:
    def __init__(self, filename=DB_NAME):
        self.connection = sqlite3.connect(filename)
        self.connection.row_factory = sqlite3.Row
        self.create_tables()

    def create_tables(self):
        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS sensor_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    battery_id TEXT,
                    cell_id TEXT,
                    timestamp TEXT,
                    temperature REAL,
                    voltage REAL,
                    current REAL,
                    coolant_temperature REAL,
                    flow_rate REAL,
                    delta_t REAL,
                    status TEXT
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS cfd_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_name TEXT,
                    reynolds REAL,
                    inlet_temperature REAL,
                    concentration REAL,
                    pressure_drop REAL,
                    heat_transfer REAL,
                    max_temperature REAL,
                    score REAL
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    model_name TEXT,
                    predicted_temperature REAL,
                    observed_temperature REAL,
                    error REAL
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS maintenance_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    alert_type TEXT,
                    description TEXT,
                    status TEXT
                )
            """)

    def save_reading(self, reading, delta_t, status):
        with self.connection:
            self.connection.execute("""
                INSERT INTO sensor_readings
                (battery_id, cell_id, timestamp, temperature, voltage,
                 current, coolant_temperature, flow_rate, delta_t, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                reading.battery_id, reading.cell_id, reading.timestamp,
                reading.temperature, reading.voltage, reading.current,
                reading.coolant_temperature, reading.flow_rate,
                delta_t, status
            ))

    def save_prediction(self, model, predicted, observed):
        with self.connection:
            self.connection.execute("""
                INSERT INTO predictions
                (timestamp, model_name, predicted_temperature,
                 observed_temperature, error)
                VALUES (?, ?, ?, ?, ?)
            """, (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                model, predicted, observed, abs(predicted - observed)
            ))

    def save_alert(self, alert_type, description):
        with self.connection:
            self.connection.execute("""
                INSERT INTO maintenance_logs
                (timestamp, alert_type, description, status)
                VALUES (?, ?, ?, ?)
            """, (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                alert_type, description, "Open"
            ))

    def rows(self, table):
        allowed = {
            "sensor_readings", "cfd_results",
            "predictions", "maintenance_logs"
        }
        if table not in allowed:
            raise ValueError("Unknown database table.")
        return self.connection.execute(
            f"SELECT * FROM {table} ORDER BY id DESC LIMIT 300"
        ).fetchall()

    def close(self):
        self.connection.close()


class ThermalDashboard(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Battery Thermal Management | KJS-CES-02")
        self.geometry("1220x790")
        self.minsize(1000, 680)
        self.configure(bg=BG)

        self.db = ThermalDatabase()
        self.readings = []
        self.latest = None
        self.temperature_sensor = TemperatureSensor()
        self.flow_sensor = CoolantFlowSensor()

        self.configure_styles()
        self.build_header()
        self.build_tabs()
        self.load_sample_data()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def configure_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)

        style.configure(
            "TLabel",
            background=BG,
            foreground=TEXT,
            font=("Arial", 10)
        )

        style.configure(
            "Title.TLabel",
            background=BG,
            foreground="#244b70",
            font=("Arial", 22, "bold")
        )

        style.configure(
            "Sub.TLabel",
            background=BG,
            foreground=MUTED,
            font=("Arial", 9)
        )

        style.configure(
            "CardTitle.TLabel",
            background=PANEL,
            foreground=MUTED,
            font=("Arial", 9, "bold")
        )

        style.configure(
            "CardValue.TLabel",
            background=PANEL,
            foreground="#244b70",
            font=("Arial", 20, "bold")
        )

        style.configure(
            "TButton",
            background=PALE_BLUE,
            foreground="#244b70",
            padding=(12, 9),
            borderwidth=0,
            font=("Arial", 10, "bold")
        )

        style.map(
            "TButton",
            background=[
                ("active", "#b8ddfb"),
                ("pressed", MID_BLUE)
            ],
            foreground=[("disabled", MUTED)]
        )

        style.configure(
            "TEntry",
            padding=7,
            fieldbackground=PANEL,
            foreground=TEXT,
            bordercolor=BORDER
        )

        style.configure(
            "TCombobox",
            padding=6,
            fieldbackground=PANEL,
            foreground=TEXT,
            background=PALE_BLUE,
            arrowcolor=ACCENT
        )

        style.configure(
            "TNotebook",
            background=BG,
            borderwidth=0
        )

        style.configure(
            "TNotebook.Tab",
            background=PALE_BLUE,
            foreground="#244b70",
            padding=(13, 10),
            font=("Arial", 9, "bold")
        )

        style.map(
            "TNotebook.Tab",
            background=[("selected", MID_BLUE)],
            foreground=[("selected", "#173b5c")]
        )

        style.configure(
            "Treeview",
            background=PANEL,
            fieldbackground=PANEL,
            foreground=TEXT,
            rowheight=29,
            borderwidth=0,
            font=("Arial", 9)
        )

        style.configure(
            "Treeview.Heading",
            background=PALE_BLUE,
            foreground="#244b70",
            font=("Arial", 9, "bold"),
            padding=7
        )

        style.map(
            "Treeview",
            background=[("selected", MID_BLUE)],
            foreground=[("selected", "#173b5c")]
        )

    def build_header(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=24, pady=(22, 12))

        left = tk.Frame(header, bg=BG)
        left.pack(side="left", fill="x", expand=True)

        tk.Label(
            left,
            text="BATTERY THERMAL MANAGEMENT",
            font=("Arial", 22, "bold"),
            bg=BG,
            fg="#244b70"
        ).pack(anchor="w")

        tk.Label(
            left,
            text="KJS-CES-02  •  8 SCENARIOS  •  PYTHON + SQLITE",
            font=("Arial", 10),
            bg=BG,
            fg=MUTED
        ).pack(anchor="w", pady=(5, 0))

        tk.Label(
            header,
            text="● DEMO MODE",
            font=("Arial", 10, "bold"),
            bg="#e0f5ea",
            fg="#24784e",
            padx=13,
            pady=8
        ).pack(side="right", anchor="n")

    def create_tab(self, title):
        frame = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(frame, text=title)
        return frame

    def build_tabs(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=22, pady=(0, 20))

        self.dashboard_tab = self.create_tab("Overview")
        self.sensor_tab = self.create_tab("1. Sensor Data")
        self.cooling_tab = self.create_tab("2. Cooling Analysis")
        self.nanofluid_tab = self.create_tab("3. Fluids")
        self.prediction_tab = self.create_tab("4. Prediction")
        self.twin_tab = self.create_tab("5. Digital Twin")
        self.monitor_tab = self.create_tab("6. Monitoring")
        self.database_tab = self.create_tab("7. Database")
        self.recommend_tab = self.create_tab("8. Recommendations")

        self.build_dashboard_tab()
        self.build_sensor_tab()
        self.build_cooling_tab()
        self.build_nanofluid_tab()
        self.build_prediction_tab()
        self.build_twin_tab()
        self.build_monitor_tab()
        self.build_database_tab()
        self.build_recommend_tab()

    def card(self, parent, title, value, column):
        frame = tk.Frame(
            parent, bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=15, pady=15
        )
        frame.grid(row=0, column=column, sticky="nsew", padx=5)

        tk.Label(
            frame, text=title.upper(),
            bg=PANEL, fg=MUTED,
            font=("Arial", 9, "bold")
        ).pack(anchor="w")

        label = tk.Label(
            frame, text=value,
            bg=PANEL, fg="#244b70",
            font=("Arial", 20, "bold")
        )
        label.pack(anchor="w", pady=(10, 0))

        parent.columnconfigure(column, weight=1)
        return label

    def build_dashboard_tab(self):
        cards = tk.Frame(self.dashboard_tab, bg=BG)
        cards.pack(fill="x", pady=(0, 16))

        self.temp_card = self.card(cards, "Battery Temperature", "-- °C", 0)
        self.volt_card = self.card(cards, "Voltage", "-- V", 1)
        self.current_card = self.card(cards, "Current", "-- A", 2)
        self.flow_card = self.card(cards, "Coolant Flow", "-- L/min", 3)

        self.status_label = tk.Label(
            self.dashboard_tab,
            text="STATUS: WAITING FOR DATA",
            bg=PALE_BLUE,
            fg="#244b70",
            font=("Arial", 12, "bold"),
            padx=14, pady=12,
            anchor="w"
        )
        self.status_label.pack(fill="x", pady=(0, 14))

        tk.Label(
            self.dashboard_tab,
            text="LATEST SENSOR READING",
            bg=BG, fg="#244b70",
            font=("Arial", 11, "bold")
        ).pack(anchor="w", pady=(5, 8))

        self.latest_text = tk.Text(
            self.dashboard_tab,
            height=4,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            wrap="word",
            font=("Consolas", 10),
            padx=12, pady=12,
            highlightbackground=BORDER,
            highlightthickness=1
        )
        self.latest_text.pack(fill="x")

        actions = ttk.Frame(self.dashboard_tab)
        actions.pack(fill="x", pady=16)

        ttk.Button(
            actions, text="Load Sample Data",
            command=self.load_sample_data
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            actions, text="Refresh Dashboard",
            command=self.refresh_dashboard
        ).pack(side="left", padx=8)

        ttk.Button(
            actions, text="View Summary",
            command=self.show_summary
        ).pack(side="left", padx=8)

        ttk.Label(
            self.dashboard_tab,
            text="Educational simulation. Thresholds must be verified for the actual battery.",
            style="Sub.TLabel"
        ).pack(anchor="w", pady=8)

    def build_sensor_tab(self):
        form = ttk.Frame(self.sensor_tab)
        form.pack(fill="x", pady=(0, 12))

        fields = [
            ("Battery ID", "BAT-01"),
            ("Cell ID", "CELL-01"),
            ("Temperature °C", "38.5"),
            ("Voltage V", "3.7"),
            ("Current A", "12.0"),
            ("Coolant temp °C", "25.0"),
            ("Flow L/min", "2.4")
        ]

        self.sensor_vars = {}

        for i, (label, default) in enumerate(fields):
            col = i % 4
            row = i // 4

            cell = ttk.Frame(form)
            cell.grid(
                row=row, column=col,
                sticky="ew", padx=6, pady=7
            )

            ttk.Label(cell, text=label).pack(anchor="w")
            var = tk.StringVar(value=default)

            ttk.Entry(
                cell, textvariable=var, width=20
            ).pack(fill="x", pady=(4, 0))

            self.sensor_vars[label] = var
            form.columnconfigure(col, weight=1)

        ttk.Button(
            form, text="Validate & Save Reading",
            command=self.add_manual_reading
        ).grid(row=2, column=0, sticky="w", padx=5, pady=10)

        ttk.Button(
            form, text="Insert Test Reading",
            command=self.insert_random_reading
        ).grid(row=2, column=1, sticky="w", padx=5, pady=10)

        self.reading_tree = self.make_tree(
            self.sensor_tab,
            ["ID", "Time", "Battery/Cell", "Temp °C",
             "Voltage V", "Current A", "Coolant °C",
             "Flow L/min", "Delta T °C", "Status"],
            height=13
        )

    def build_cooling_tab(self):
        ttk.Label(
            self.cooling_tab,
            text="Micro-channel Cooling Performance",
            font=("Arial", 14, "bold")
        ).pack(anchor="w", pady=8)

        ttk.Label(
            self.cooling_tab,
            text="Illustrative configurations, not measured CFD results.",
            style="Sub.TLabel"
        ).pack(anchor="w", pady=5)

        ttk.Button(
            self.cooling_tab,
            text="Analyze & Rank Configurations",
            command=self.analyze_cooling
        ).pack(anchor="w", pady=10)

        self.cooling_output = self.make_text(self.cooling_tab)

    def build_nanofluid_tab(self):
        ttk.Label(
            self.nanofluid_tab,
            text="Water vs Al₂O₃/Water Nanofluid",
            font=("Arial", 14, "bold")
        ).pack(anchor="w", pady=8)

        ttk.Button(
            self.nanofluid_tab,
            text="Compare Cooling Fluids",
            command=self.compare_fluids
        ).pack(anchor="w", pady=10)

        self.fluid_output = self.make_text(self.nanofluid_tab)

    def build_prediction_tab(self):
        ttk.Label(
            self.prediction_tab,
            text="Temperature Risk Estimation",
            font=("Arial", 14, "bold")
        ).pack(anchor="w", pady=8)

        self.pred_vars = {}
        form = ttk.Frame(self.prediction_tab)
        form.pack(anchor="w")

        fields = [
            ("Battery temperature °C", "38.5"),
            ("Current A", "12"),
            ("Coolant temperature °C", "25"),
            ("Flow L/min", "2.4")
        ]

        for i, (label, default) in enumerate(fields):
            box = ttk.Frame(form)
            box.grid(
                row=i // 2, column=i % 2,
                padx=8, pady=8, sticky="w"
            )

            ttk.Label(box, text=label).pack(anchor="w")
            var = tk.StringVar(value=default)
            ttk.Entry(box, textvariable=var, width=24).pack(pady=5)
            self.pred_vars[label] = var

        ttk.Button(
            self.prediction_tab,
            text="Estimate Temperature Risk",
            command=self.predict_temperature
        ).pack(anchor="w", pady=12)

        self.prediction_output = tk.Label(
            self.prediction_tab,
            text="Enter conditions and run the demonstration predictor.",
            bg=PANEL, fg=TEXT,
            justify="left", anchor="w",
            font=("Arial", 12),
            padx=15, pady=15,
            highlightbackground=BORDER,
            highlightthickness=1
        )
        self.prediction_output.pack(fill="x", pady=10)

    def build_twin_tab(self):
        ttk.Label(
            self.twin_tab,
            text="Digital Twin Simulator",
            font=("Arial", 14, "bold")
        ).pack(anchor="w", pady=8)

        ttk.Label(
            self.twin_tab,
            text="Compare predicted and observed temperatures using demonstration data.",
            style="Sub.TLabel"
        ).pack(anchor="w", pady=8)

        form = ttk.Frame(self.twin_tab)
        form.pack(anchor="w")

        self.twin_pred = tk.StringVar(value="40.0")
        self.twin_obs = tk.StringVar(value="38.5")

        for i, (label, var) in enumerate([
            ("Predicted temperature °C", self.twin_pred),
            ("Observed temperature °C", self.twin_obs)
        ]):
            box = ttk.Frame(form)
            box.grid(row=0, column=i, padx=8, pady=5)

            ttk.Label(box, text=label).pack(anchor="w")
            ttk.Entry(box, textvariable=var, width=24).pack(pady=5)

        ttk.Button(
            self.twin_tab,
            text="Compare & Save History",
            command=self.compare_twin
        ).pack(anchor="w", pady=12)

        self.twin_output = tk.Label(
            self.twin_tab,
            text="Prediction error will appear here.",
            bg=PANEL, fg=TEXT,
            font=("Arial", 12),
            padx=15, pady=15,
            highlightbackground=BORDER,
            highlightthickness=1
        )
        self.twin_output.pack(fill="x", pady=8)

    def build_monitor_tab(self):
        ttk.Label(
            self.monitor_tab,
            text="Thermal Monitoring Center",
            font=("Arial", 14, "bold")
        ).pack(anchor="w", pady=5)

        ttk.Label(
            self.monitor_tab,
            text="The chart displays saved demonstration readings, not live sensors.",
            style="Sub.TLabel"
        ).pack(anchor="w", pady=5)

        controls = ttk.Frame(self.monitor_tab)
        controls.pack(fill="x", pady=8)

        ttk.Button(
            controls, text="Normal Test",
            command=lambda: self.add_test_case(34.0, 2.8)
        ).pack(side="left", padx=4)

        ttk.Button(
            controls, text="Warning Test",
            command=lambda: self.add_test_case(47.0, 2.0)
        ).pack(side="left", padx=4)

        ttk.Button(
            controls, text="Critical Test",
            command=lambda: self.add_test_case(52.0, 0.7)
        ).pack(side="left", padx=4)

        ttk.Button(
            controls, text="Export CSV",
            command=self.export_readings_csv
        ).pack(side="right", padx=4)

        self.monitor_summary = ttk.Label(
            self.monitor_tab,
            text="No readings yet"
        )
        self.monitor_summary.pack(anchor="w", pady=8)

        self.trend_canvas = tk.Canvas(
            self.monitor_tab,
            height=300,
            bg=PANEL,
            highlightthickness=1,
            highlightbackground=BORDER
        )
        self.trend_canvas.pack(fill="both", expand=True)
        self.trend_canvas.bind(
            "<Configure>",
            lambda event: self.draw_temperature_trend()
        )

    def build_database_tab(self):
        ttk.Label(
            self.database_tab,
            text="SQLite Database Records",
            font=("Arial", 14, "bold")
        ).pack(anchor="w", pady=8)

        bar = ttk.Frame(self.database_tab)
        bar.pack(fill="x", pady=8)

        self.db_table_var = tk.StringVar(value="sensor_readings")

        selector = ttk.Combobox(
            bar,
            textvariable=self.db_table_var,
            state="readonly",
            values=[
                "sensor_readings", "cfd_results",
                "predictions", "maintenance_logs"
            ],
            width=24
        )
        selector.pack(side="left", padx=4)
        selector.bind(
            "<<ComboboxSelected>>",
            lambda event: self.refresh_database_tree()
        )

        ttk.Button(
            bar, text="Load Records",
            command=self.refresh_database_tree
        ).pack(side="left", padx=4)

        ttk.Button(
            bar, text="Delete Selected Reading",
            command=self.delete_selected_reading
        ).pack(side="left", padx=4)

        self.db_tree = ttk.Treeview(
            self.database_tab, show="headings", height=18
        )

        scrollbar = ttk.Scrollbar(
            self.database_tab,
            orient="vertical",
            command=self.db_tree.yview
        )

        self.db_tree.configure(yscrollcommand=scrollbar.set)
        self.db_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def build_recommend_tab(self):
        ttk.Label(
            self.recommend_tab,
            text="Cooling Recommendations & Predictive Maintenance",
            font=("Arial", 14, "bold")
        ).pack(anchor="w", pady=8)

        ttk.Label(
            self.recommend_tab,
            text="Recommendations use demonstration rules only.",
            style="Sub.TLabel"
        ).pack(anchor="w", pady=5)

        ttk.Button(
            self.recommend_tab,
            text="Generate Recommendation",
            command=self.generate_recommendation
        ).pack(anchor="w", pady=8)

        self.recommend_output = self.make_text(
            self.recommend_tab, height=7
        )
        self.recommend_output.pack(fill="x", pady=8)

        ttk.Label(
            self.recommend_tab,
            text="Recent Maintenance Alerts",
            font=("Arial", 11, "bold")
        ).pack(anchor="w", pady=5)

        self.alert_tree = self.make_tree(
            self.recommend_tab,
            ["ID", "Time", "Type", "Description", "Status"],
            height=8
        )

    def make_text(self, parent, height=15):
        widget = tk.Text(
            parent,
            height=height,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            wrap="word",
            font=("Consolas", 10),
            padx=12, pady=12,
            highlightbackground=BORDER,
            highlightthickness=1
        )
        widget.pack(fill="both", expand=True)
        return widget

    def make_tree(self, parent, columns, height=10):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)

        tree = ttk.Treeview(
            frame, columns=columns,
            show="headings", height=height
        )

        for column in columns:
            tree.heading(column, text=column)
            tree.column(
                column, width=105,
                minwidth=70, stretch=True
            )

        yscroll = ttk.Scrollbar(
            frame, orient="vertical", command=tree.yview
        )
        xscroll = ttk.Scrollbar(
            frame, orient="horizontal", command=tree.xview
        )

        tree.configure(
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set
        )

        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")

        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    def get_status(self, temperature):
        if temperature >= TEMP_CRITICAL:
            return "CRITICAL"
        if temperature > TEMP_WARNING:
            return "WARNING"
        return "NORMAL"

    def make_demo_reading(self, temperature=None, flow=None):
        return SensorReading(
            "BAT-01",
            f"CELL-{len(self.readings) + 1:02d}",
            temperature if temperature is not None else round(random.uniform(30, 48), 1),
            round(random.uniform(3.55, 4.15), 2),
            round(random.uniform(5, 25), 1),
            round(random.uniform(21, 30), 1),
            flow if flow is not None else round(random.uniform(1, 3.5), 2)
        )

    def persist_reading(self, reading):
        delta = ThermalAnalysis.temperature_difference(
            reading.temperature, reading.coolant_temperature
        )
        self.db.save_reading(
            reading, delta, self.get_status(reading.temperature)
        )

    def load_sample_data(self):
        if not self.readings:
            self.readings = [
                self.make_demo_reading(34.2, 2.8),
                self.make_demo_reading(39.6, 2.2),
                self.make_demo_reading(46.4, 1.1)
            ]

            for reading in self.readings:
                self.persist_reading(reading)

        self.latest = self.readings[-1]
        self.refresh_all_views()

    def add_manual_reading(self):
        try:
            v = self.sensor_vars

            reading = SensorReading(
                v["Battery ID"].get().strip(),
                v["Cell ID"].get().strip(),
                float(v["Temperature °C"].get()),
                float(v["Voltage V"].get()),
                float(v["Current A"].get()),
                float(v["Coolant temp °C"].get()),
                float(v["Flow L/min"].get())
            )

            if reading.temperature > 150:
                raise ValueError("Temperature exceeds the demo input limit.")
            if reading.voltage <= 0:
                raise ValueError("Voltage must be greater than zero.")

            self.readings.append(reading)
            self.latest = reading
            self.persist_reading(reading)
            self.refresh_all_views()

            messagebox.showinfo("Saved", "Reading saved successfully.")

        except (ValueError, TypeError) as error:
            messagebox.showerror("Invalid Input", str(error))
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", str(error))

    def insert_random_reading(self):
        try:
            reading = self.make_demo_reading()
            self.readings.append(reading)
            self.latest = reading
            self.persist_reading(reading)
            self.refresh_all_views()
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", str(error))

    def add_test_case(self, temperature, flow):
        try:
            reading = self.make_demo_reading(temperature, flow)
            self.readings.append(reading)
            self.latest = reading
            self.persist_reading(reading)
            self.refresh_all_views()
            self.notebook.select(self.monitor_tab)
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", str(error))

    def refresh_all_views(self):
        self.refresh_dashboard()
        self.refresh_readings_tree()
        self.refresh_database_tree()
        self.refresh_alert_tree()
        self.draw_temperature_trend()

    def refresh_dashboard(self):
        if not self.latest:
            return

        r = self.latest
        delta = abs(r.temperature - r.coolant_temperature)
        status = self.get_status(r.temperature)

        self.temp_card.configure(text=f"{r.temperature:.1f} °C")
        self.volt_card.configure(text=f"{r.voltage:.2f} V")
        self.current_card.configure(text=f"{r.current:.1f} A")
        self.flow_card.configure(text=f"{r.flow_rate:.2f} L/min")

        colors = {
            "NORMAL": ("#e0f5ea", "#24784e"),
            "WARNING": ("#fff3d6", "#946200"),
            "CRITICAL": ("#ffe5e8", "#c4344d")
        }

        bg, fg = colors[status]

        self.status_label.configure(
            text=f"STATUS: {status}  |  ΔT {delta:.1f} °C",
            bg=bg, fg=fg
        )

        self.latest_text.delete("1.0", tk.END)
        self.latest_text.insert(
            tk.END,
            r.summary() + f"\nTimestamp: {r.timestamp}"
        )

    def refresh_readings_tree(self):
        self.reading_tree.delete(*self.reading_tree.get_children())

        for row in self.db.rows("sensor_readings"):
            self.reading_tree.insert(
                "", "end",
                values=(
                    row["id"], row["timestamp"],
                    f'{row["battery_id"]}/{row["cell_id"]}',
                    f'{row["temperature"]:.1f}',
                    f'{row["voltage"]:.2f}',
                    f'{row["current"]:.1f}',
                    f'{row["coolant_temperature"]:.1f}',
                    f'{row["flow_rate"]:.2f}',
                    f'{row["delta_t"]:.1f}',
                    row["status"]
                )
            )

    def show_summary(self):
        rows = self.db.rows("sensor_readings")

        if not rows:
            messagebox.showinfo("Summary", "No readings saved.")
            return

        temperatures = list(
            map(lambda row: float(row["temperature"]), rows)
        )

        messagebox.showinfo(
            "Reading Summary",
            f"Records: {len(rows)}\n"
            f"Average: {sum(temperatures) / len(temperatures):.2f} °C\n"
            f"Maximum: {max(temperatures):.2f} °C\n"
            f"Minimum: {min(temperatures):.2f} °C"
        )

    def analyze_cooling(self):
        cases = [
            {
                "name": "Configuration A", "flow": 1.0,
                "inlet": 25.0, "outlet": 42.0,
                "pressure": 18.0, "htc": 420.0
            },
            {
                "name": "Configuration B", "flow": 2.0,
                "inlet": 25.0, "outlet": 37.0,
                "pressure": 24.0, "htc": 510.0
            },
            {
                "name": "Configuration C", "flow": 3.0,
                "inlet": 24.0, "outlet": 35.5,
                "pressure": 37.0, "htc": 560.0
            }
        ]

        for case in cases:
            case["delta_t"] = ThermalAnalysis.temperature_difference(
                case["outlet"], case["inlet"]
            )
            case["score"] = (
                case["htc"] - case["pressure"] * 2
                - case["delta_t"] * 3
            )

        ranked = ThermalAnalysis.rank_cases(cases)

        self.cooling_output.delete("1.0", tk.END)
        self.cooling_output.insert(
            tk.END,
            "SYNTHETIC EXAMPLE DATA — NOT CFD MEASUREMENTS\n\n"
        )

        for i, case in enumerate(ranked, 1):
            self.cooling_output.insert(
                tk.END,
                f"{i}. {case['name']}\n"
                f"Flow: {case['flow']} L/min\n"
                f"Temperature difference: {case['delta_t']:.1f} °C\n"
                f"Pressure drop: {case['pressure']}\n"
                f"Heat-transfer coefficient: {case['htc']}\n"
                f"Demonstration score: {case['score']:.2f}\n\n"
            )

    def compare_fluids(self):
        fluids = [
            WaterCase("Water", 0, 1800, 25, 20, 430, 43),
            NanofluidCase("Al2O3/Water 0.5%", 0.5, 2100, 25, 25, 520, 39),
            NanofluidCase("Al2O3/Water 1.0%", 1.0, 2300, 25, 34, 560, 37)
        ]

        cases = list(map(
            lambda fluid: {
                "name": fluid.name,
                "concentration": fluid.concentration,
                "reynolds": fluid.reynolds,
                "inlet": fluid.inlet_temp,
                "pressure": fluid.pressure_drop,
                "htc": fluid.heat_transfer,
                "max_temp": fluid.max_temp,
                "score": fluid.performance_score()
            },
            fluids
        ))

        filtered = list(
            filter(lambda case: case["pressure"] <= 35, cases)
        )

        ranked = sorted(
            filtered, key=lambda case: case["score"], reverse=True
        )

        self.fluid_output.delete("1.0", tk.END)
        self.fluid_output.insert(
            tk.END,
            "SYNTHETIC EXAMPLE DATA — NOT EXPERIMENTAL RESULTS\n\n"
        )

        for i, case in enumerate(ranked, 1):
            self.fluid_output.insert(
                tk.END,
                f"{i}. {case['name']}\n"
                f"Concentration: {case['concentration']}%\n"
                f"Reynolds number: {case['reynolds']}\n"
                f"Inlet temperature: {case['inlet']} °C\n"
                f"Pressure drop: {case['pressure']}\n"
                f"Heat-transfer coefficient: {case['htc']}\n"
                f"Maximum temperature: {case['max_temp']} °C\n"
                f"Performance score: {case['score']:.2f}\n\n"
            )

    def predict_temperature(self):
        try:
            values = {
                key: float(value.get())
                for key, value in self.pred_vars.items()
            }

            if any(value < 0 for value in values.values()):
                raise ValueError("Inputs cannot be negative.")

            predicted = (
                values["Battery temperature °C"]
                + max(0, values["Current A"] - 10) * 0.08
                + max(0, 2 - values["Flow L/min"]) * 1.4
                + max(0, values["Coolant temperature °C"] - 25) * 0.15
            )

            risk = self.get_status(predicted)

            self.prediction_output.configure(
                text=(
                    "MODEL: RULE-BASED DEMONSTRATION\n\n"
                    f"Estimated temperature: {predicted:.2f} °C\n"
                    f"Risk category: {risk}\n\n"
                    "This is not a trained or validated AI model."
                )
            )

            observed = self.latest.temperature if self.latest else predicted
            self.db.save_prediction(
                "Rule-Based Demonstration", predicted, observed
            )
            self.refresh_database_tree()

        except (ValueError, TypeError) as error:
            messagebox.showerror("Invalid Input", str(error))
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", str(error))

    def compare_twin(self):
        try:
            predicted = float(self.twin_pred.get())
            observed = float(self.twin_obs.get())

            if predicted < 0 or observed < 0:
                raise ValueError("Temperatures cannot be negative.")

            error = abs(predicted - observed)

            self.db.save_prediction(
                "Digital Twin Demonstration", predicted, observed
            )

            self.twin_output.configure(
                text=(
                    f"Predicted: {predicted:.2f} °C\n"
                    f"Observed: {observed:.2f} °C\n"
                    f"Absolute error: {error:.2f} °C"
                )
            )
            self.refresh_database_tree()

        except (ValueError, TypeError) as error:
            messagebox.showerror("Invalid Input", str(error))
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", str(error))

    def generate_recommendation(self):
        if not self.latest:
            messagebox.showwarning(
                "No Data", "Enter a sensor reading first."
            )
            return

        reading = self.latest
        status = self.get_status(reading.temperature)

        if status == "CRITICAL":
            kind = "High Temperature"
            description = (
                "Critical demonstration threshold crossed. "
                "Inspect the cooling system and follow approved safety procedures."
            )
        elif status == "WARNING":
            kind = "Temperature Warning"
            description = (
                "Temperature exceeds the demonstration threshold. "
                "Review coolant flow and recent readings."
            )
        elif reading.flow_rate < 1.5:
            kind = "Low Coolant Flow"
            description = (
                "Flow is below the demonstration threshold. "
                "Inspect the flow sensor and cooling path."
            )
        elif abs(
            reading.temperature - reading.coolant_temperature
        ) >= TARGET_DELTA_T:
            kind = "Thermal Gradient"
            description = (
                "Review the battery-to-coolant temperature difference "
                "and compare cell temperatures."
            )
        else:
            kind = "Normal Monitoring"
            description = (
                "No configured demonstration rule was triggered. "
                "Continue monitoring."
            )

        self.db.save_alert(kind, description)

        self.recommend_output.delete("1.0", tk.END)
        self.recommend_output.insert(
            tk.END,
            f"Alert type: {kind}\n"
            f"Status: {status}\n"
            f"Recommendation: {description}\n\n"
            "Educational demonstration rules only."
        )

        self.refresh_alert_tree()
        self.refresh_database_tree()

    def draw_temperature_trend(self):
        if not hasattr(self, "trend_canvas"):
            return

        canvas = self.trend_canvas
        canvas.delete("all")

        width = max(canvas.winfo_width(), 500)
        height = max(canvas.winfo_height(), 250)
        left, right, top, bottom = 58, width - 25, 25, height - 42

        canvas.create_text(
            18, 16, text="°C", fill=TEXT, anchor="w"
        )

        for value in (0, 15, 30, 45, 60):
            y = bottom - (value / 60) * (bottom - top)

            canvas.create_line(
                left, y, right, y,
                fill=BORDER, dash=(3, 4)
            )
            canvas.create_text(
                left - 10, y, text=str(value),
                fill=MUTED, anchor="e"
            )

        canvas.create_line(
            left, top, left, bottom, fill=MUTED
        )
        canvas.create_line(
            left, bottom, right, bottom, fill=MUTED
        )

        rows = list(reversed(self.db.rows("sensor_readings")))[:20]

        if not rows:
            canvas.create_text(
                width / 2, height / 2,
                text="Save a reading to display the trend",
                fill=TEXT
            )
            self.monitor_summary.configure(text="No readings available")
            return

        points = []

        for index, row in enumerate(rows):
            x = left + (
                index / max(len(rows) - 1, 1)
            ) * (right - left)

            temp = float(row["temperature"])
            y = bottom - (
                min(max(temp, 0), 60) / 60
            ) * (bottom - top)

            points.extend((x, y))

        if len(points) >= 4:
            canvas.create_line(
                *points, fill=ACCENT,
                width=3, smooth=True
            )

        for i in range(0, len(points), 2):
            x, y = points[i], points[i + 1]
            canvas.create_oval(
                x - 4, y - 4, x + 4, y + 4,
                fill=ACCENT, outline=""
            )

        temps = [float(row["temperature"]) for row in rows]

        self.monitor_summary.configure(
            text=(
                f"Readings: {len(rows)}  |  Latest: {temps[-1]:.1f} °C  |  "
                f"Minimum: {min(temps):.1f} °C  |  "
                f"Maximum: {max(temps):.1f} °C"
            )
        )

    def export_readings_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            title="Export sensor readings"
        )

        if not path:
            return

        try:
            rows = self.db.rows("sensor_readings")

            if not rows:
                messagebox.showinfo("Export", "No readings to export.")
                return

            with open(
                path, "w", newline="", encoding="utf-8"
            ) as file:
                writer = csv.writer(file)
                writer.writerow(rows[0].keys())
                writer.writerows([tuple(row) for row in rows])

            messagebox.showinfo(
                "Export Complete",
                f"Exported {len(rows)} readings."
            )

        except (OSError, sqlite3.Error) as error:
            messagebox.showerror("Export Error", str(error))

    def refresh_database_tree(self):
        if not hasattr(self, "db_tree"):
            return

        try:
            rows = self.db.rows(self.db_table_var.get())
            self.db_tree.delete(*self.db_tree.get_children())

            if rows:
                columns = list(rows[0].keys())
                self.db_tree["columns"] = columns

                for column in columns:
                    self.db_tree.heading(column, text=column)
                    self.db_tree.column(
                        column, width=125, minwidth=75
                    )

                for row in rows:
                    self.db_tree.insert(
                        "", "end",
                        values=tuple(row[column] for column in columns)
                    )
            else:
                self.db_tree["columns"] = ["message"]
                self.db_tree.heading("message", text="Message")
                self.db_tree.insert(
                    "", "end", values=("No records yet",)
                )

        except sqlite3.Error as error:
            messagebox.showerror("Database Error", str(error))

    def delete_selected_reading(self):
        if self.db_table_var.get() != "sensor_readings":
            messagebox.showinfo(
                "Delete",
                "Select the sensor_readings table first."
            )
            return

        selected = self.db_tree.selection()

        if not selected:
            messagebox.showwarning(
                "Select Record", "Select a reading first."
            )
            return

        if not messagebox.askyesno(
            "Confirm", "Delete the selected reading?"
        ):
            return

        try:
            values = self.db_tree.item(selected[0], "values")

            with self.db.connection:
                self.db.connection.execute(
                    "DELETE FROM sensor_readings WHERE id = ?",
                    (int(values[0]),)
                )

            remaining = self.db.rows("sensor_readings")

            if remaining:
                row = remaining[0]
                self.latest = SensorReading(
                    row["battery_id"],
                    row["cell_id"],
                    row["temperature"],
                    row["voltage"],
                    row["current"],
                    row["coolant_temperature"],
                    row["flow_rate"],
                    row["timestamp"]
                )
            else:
                self.latest = None

            self.refresh_all_views()

        except (ValueError, sqlite3.Error) as error:
            messagebox.showerror("Delete Error", str(error))

    def refresh_alert_tree(self):
        if not hasattr(self, "alert_tree"):
            return

        self.alert_tree.delete(*self.alert_tree.get_children())

        for row in self.db.rows("maintenance_logs"):
            self.alert_tree.insert(
                "", "end",
                values=(
                    row["id"], row["timestamp"],
                    row["alert_type"], row["description"],
                    row["status"]
                )
            )

    def refresh_all_views(self):
        self.refresh_dashboard()
        self.refresh_readings_tree()
        self.refresh_database_tree()
        self.refresh_alert_tree()
        self.draw_temperature_trend()

    def on_close(self):
        self.db.close()
        self.destroy()


if __name__ == "__main__":
    try:
        app = ThermalDashboard()
        app.mainloop()
    except sqlite3.Error as error:
        messagebox.showerror("Database Startup Error", str(error))