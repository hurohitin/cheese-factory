from datetime import date, datetime, timedelta
import ctypes
from collections import defaultdict
import hashlib
import hmac
import os
from tkinter import messagebox

import customtkinter as ctk
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from database import BASE_DIR, Base, SessionLocal, engine
from models import Batch, CheeseType, Order, OrderItem, Shipment, WriteOff
from neural_forecast import train_and_forecast


PASSWORD_ITERATIONS = 200_000
MAKER_SALT = b"cheese-app-maker-v1"
CUSTOMER_SALT = b"cheese-app-customer-v1"
MAKER_PASSWORD_HASH = "b23f92afe61cd5347b3e23c1ba6ef5ef4ce8f2159af277da7c6431de0b689e9b"
CUSTOMER_PASSWORD_HASH = "cc87a45647742235eceee2ce9e51bba2a2fbdadafd180ec4406372a77262de40"
ORDER_WAITING = "Ожидает подтверждения"
SWAMP_COLOR = "#667A3E"
SWAMP_HOVER = "#526331"
BURGUNDY_COLOR = "#7A263A"
BURGUNDY_HOVER = "#611D2E"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def password_matches(password, salt, expected_hash):
    actual_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    ).hex()
    return hmac.compare_digest(actual_hash, expected_hash)


def apply_dark_titlebar(window):
    if os.name != "nt":
        return

    def apply():
        try:
            window.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            enabled = ctypes.c_int(1)
            for attribute in (20, 19):
                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)
                )
                if result == 0:
                    break
        except (AttributeError, OSError):
            pass

    window.after(10, apply)


def center_window(window, width, height):
    window.update_idletasks()
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


def batch_dates(batch):
    ready = batch.production_date + timedelta(days=batch.cheese_type.maturation_days)
    expires = batch.production_date + timedelta(days=batch.cheese_type.shelf_life_days)
    return ready, expires


def batch_status(batch):
    ready, expires = batch_dates(batch)
    today = date.today()
    if batch.remaining_heads <= 0:
        return "Реализована"
    if today < ready:
        return "Созревает"
    if today > expires:
        return "Просрочена"
    if (expires - today).days <= 14:
        return "Реализовать первой"
    return "Готова к продаже"


def clear_window(window):
    for widget in window.winfo_children():
        widget.destroy()


def heading(parent, text, size=25):
    ctk.CTkLabel(
        parent, text=text, font=ctk.CTkFont(size=size, weight="bold")
    ).pack(pady=(18, 12))


def field(parent, label, placeholder=""):
    ctk.CTkLabel(parent, text=label).pack(anchor="w", padx=20)
    entry = ctk.CTkEntry(parent, placeholder_text=placeholder)
    entry.pack(fill="x", padx=20, pady=(3, 10))
    return entry


def waiting_orders_count():
    with SessionLocal() as session:
        return session.scalar(
            select(func.count(Order.id)).where(Order.status == ORDER_WAITING)
        ) or 0


class CheeseApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Информационная система сырозавода")
        self.geometry("1180x720")
        self.minsize(1000, 620)
        apply_dark_titlebar(self)
        self.show_main_menu()

    def show_main_menu(self):
        clear_window(self)
        self.resizable(False, False)
        self.geometry("700x740")
        frame = ctk.CTkFrame(self, width=560, height=590)
        frame.place(relx=0.5, rely=0.5, anchor="center")
        frame.pack_propagate(False)
        ctk.CTkLabel(
            frame,
            text="ОАО КОБРИНСКИЙ МСЗ",
            font=ctk.CTkFont(size=42, weight="bold"),
        ).pack(pady=(78, 18))
        ctk.CTkLabel(
            frame,
            text="Система учёта продукции и заказов",
            font=ctk.CTkFont(size=20),
        ).pack(pady=(0, 42))
        ctk.CTkButton(
            frame, text="Сыродел", height=66,
            font=ctk.CTkFont(size=22), command=self.show_login
        ).pack(
            fill="x", padx=62, pady=9
        )
        ctk.CTkButton(
            frame, text="Заказчик", height=66,
            font=ctk.CTkFont(size=22),
            command=lambda: self.show_login("customer")
        ).pack(fill="x", padx=62, pady=9)
        ctk.CTkButton(
            frame,
            text="Выход",
            height=66,
            font=ctk.CTkFont(size=22),
            fg_color="#64748b",
            hover_color="#475569",
            command=self.destroy,
        ).pack(fill="x", padx=62, pady=9)

    def show_login(self, role="maker"):
        clear_window(self)
        self.resizable(False, False)
        self.geometry("700x600")
        frame = ctk.CTkFrame(self, width=540, height=450)
        frame.place(relx=0.5, rely=0.5, anchor="center")
        frame.pack_propagate(False)
        role_title = "сыродела" if role == "maker" else "заказчика"
        heading(frame, f"Вход для {role_title}", size=34)
        ctk.CTkLabel(
            frame, text="Введите пароль", font=ctk.CTkFont(size=21)
        ).pack(pady=(28, 8))
        password_row = ctk.CTkFrame(frame, fg_color="transparent")
        password_row.pack(pady=5)
        password = ctk.CTkEntry(
            password_row, show="•", width=330, height=50,
            font=ctk.CTkFont(size=20)
        )
        password.pack(side="left")
        password_visible = False

        def toggle_password():
            nonlocal password_visible
            password_visible = not password_visible
            password.configure(show="" if password_visible else "•")

        ctk.CTkButton(
            password_row, text="👁", width=52, height=50,
            font=ctk.CTkFont(size=20), command=toggle_password
        ).pack(side="left", padx=(5, 0))
        password.focus()

        def login(_event=None):
            if role == "maker":
                valid = password_matches(password.get(), MAKER_SALT, MAKER_PASSWORD_HASH)
            else:
                valid = password_matches(
                    password.get(), CUSTOMER_SALT, CUSTOMER_PASSWORD_HASH
                )
            if valid:
                self.show_maker() if role == "maker" else self.show_customer()
            else:
                messagebox.showerror("Ошибка", "Неверный пароль")
                password.delete(0, "end")

        password.bind("<Return>", login)
        ctk.CTkButton(
            frame, text="Войти", width=390, height=58,
            font=ctk.CTkFont(size=21), command=login
        ).pack(pady=(22, 8))
        ctk.CTkButton(
            frame, text="Назад", width=390, height=58,
            font=ctk.CTkFont(size=21), fg_color="#64748b",
            command=self.show_main_menu
        ).pack(pady=8)

    def show_maker(self):
        clear_window(self)
        self.resizable(True, True)
        self.geometry("1180x720")
        heading(self, "Раздел сыродела")
        toolbar = ctk.CTkFrame(self)
        toolbar.pack(fill="x", padx=20, pady=(0, 10))
        for text, command in (
            ("Добавить сыр", self.open_add_cheese),
            ("Заказы", self.open_orders),
            ("Анализ", self.open_production_analysis),
            ("Обновить склад", self.show_maker),
            ("Главное меню", self.show_main_menu),
        ):
            is_add_button = text == "Добавить сыр"
            button_holder = ctk.CTkFrame(
                toolbar,
                fg_color="transparent",
            )
            button_holder.pack(side="left", padx=7, pady=10)
            toolbar_button = ctk.CTkButton(
                button_holder,
                text=text,
                width=145,
                height=46,
                font=ctk.CTkFont(size=16, weight="bold"),
                fg_color=SWAMP_COLOR if is_add_button else None,
                hover_color=SWAMP_HOVER if is_add_button else None,
                command=command,
            )
            toolbar_button.pack(side="left")
            if text == "Заказы":
                ctk.CTkLabel(
                    toolbar,
                    text=f"Неподтверждённых заказов — {waiting_orders_count()}",
                    width=250,
                    height=46,
                    corner_radius=8,
                    fg_color="#343638",
                    font=ctk.CTkFont(size=15, weight="bold"),
                ).pack(side="left", padx=(2, 7), pady=10)

        headers = ["Варка", "Название / вид", "Дата", "Остаток", "Вес, кг", "Готов с", "Годен до", "Состояние", "Действие"]
        widths = [75, 180, 90, 75, 85, 90, 90, 145, 190]
        table = ctk.CTkScrollableFrame(self)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.add_table_row(table, headers, widths, header=True)

        with SessionLocal() as session:
            batches = list(session.scalars(
                select(Batch)
                .where(Batch.remaining_heads > 0)
                .options(joinedload(Batch.cheese_type))
                .order_by(Batch.production_date.desc())
            ).unique())
            data = []
            for batch in batches:
                ready, expires = batch_dates(batch)
                data.append([
                    batch.id,
                    str(batch.batch_index),
                    f"{batch.cheese_type.base_name} / {batch.cheese_type.product_form}",
                    batch.production_date.strftime("%d.%m.%Y"),
                    str(batch.remaining_heads),
                    f"{batch.remaining_weight:.2f}",
                    ready.strftime("%d.%m.%Y"),
                    expires.strftime("%d.%m.%Y"),
                    batch_status(batch),
                ])
        for row in data:
            batch_id = row.pop(0)
            table_row = self.add_table_row(table, row, widths[:-1])
            ctk.CTkButton(
                table_row,
                text="Изменить",
                width=88,
                command=lambda bid=batch_id: self.open_edit_batch(bid),
            ).pack(side="left", padx=(4, 2), pady=6)
            ctk.CTkButton(
                table_row,
                text="Списать",
                width=88,
                fg_color=BURGUNDY_COLOR,
                hover_color=BURGUNDY_HOVER,
                command=lambda bid=batch_id: self.open_write_off(bid),
            ).pack(side="left", padx=(2, 4), pady=6)
        if not data:
            ctk.CTkLabel(table, text="Сыра пока нет. Нажмите «Добавить сыр».").pack(pady=40)

    @staticmethod
    def add_table_row(parent, values, widths, header=False):
        row = ctk.CTkFrame(parent, fg_color="#334155" if header else None)
        row.pack(fill="x", pady=2)
        for value, width in zip(values, widths):
            ctk.CTkLabel(
                row,
                text=value,
                width=width,
                anchor="w",
                text_color="white" if header else None,
                font=ctk.CTkFont(weight="bold") if header else None,
            ).pack(side="left", padx=4, pady=8)
        return row

    def open_production_analysis(self):
        window = ctk.CTkToplevel(self)
        window.title("Анализ производства")
        center_window(window, 1000, 700)
        window.transient(self)
        apply_dark_titlebar(window)
        heading(window, "Анализ производства")

        with SessionLocal() as session:
            batches = list(session.scalars(
                select(Batch).options(joinedload(Batch.cheese_type))
            ).unique())
            shipments = list(session.scalars(select(Shipment)))
            write_offs = list(session.scalars(select(WriteOff)))
            completed_orders = list(session.scalars(
                select(Order).where(Order.status.in_(["Отправлен", "Принят"]))
                .options(joinedload(Order.items).joinedload(OrderItem.cheese_type))
                .order_by(Order.created_at)
            ).unique())

            produced_heads = sum(batch.initial_heads for batch in batches)
            produced_weight = sum(batch.initial_weight for batch in batches)
            stock_heads = sum(batch.remaining_heads for batch in batches)
            stock_weight = sum(batch.remaining_weight for batch in batches)
            shipped_heads = sum(item.quantity_heads for item in shipments)
            written_off_heads = sum(item.quantity_heads for item in write_offs)

            production_by_type = defaultdict(int)
            stock_by_type = defaultdict(int)
            for batch in batches:
                label = f"{batch.cheese_type.base_name} / {batch.cheese_type.product_form}"
                production_by_type[label] += batch.initial_heads
                stock_by_type[label] += batch.remaining_heads

            demand_by_type = defaultdict(int)
            for order in completed_orders:
                for item in order.items:
                    label = f"{item.cheese_type.base_name} / {item.cheese_type.product_form}"
                    demand_by_type[label] += item.quantity_heads

        tabs = ctk.CTkTabview(window)
        tabs.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        for tab_name in ("Обзор", "Риски", "Прогноз", "Рекомендации"):
            tabs.add(tab_name)

        overview = tabs.tab("Обзор")
        cards = ctk.CTkFrame(overview, fg_color="transparent")
        cards.pack(fill="x", padx=10, pady=12)
        metrics = (
            ("Произведено", f"{produced_heads} гол.\n{produced_weight:.1f} кг"),
            ("На складе", f"{stock_heads} гол.\n{stock_weight:.1f} кг"),
            ("Отправлено", f"{shipped_heads} гол."),
            ("Списано", f"{written_off_heads} гол."),
        )
        for title, value in metrics:
            card = ctk.CTkFrame(cards, width=210, height=115)
            card.pack(side="left", fill="x", expand=True, padx=6)
            card.pack_propagate(False)
            ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(16, 5))
            ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=19)).pack()

        details = ctk.CTkScrollableFrame(overview)
        details.pack(fill="both", expand=True, padx=10, pady=8)
        ctk.CTkLabel(details, text="Производство и остатки по видам", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=10, pady=10)
        all_labels = sorted(set(production_by_type) | set(demand_by_type))
        for label in all_labels:
            ctk.CTkLabel(
                details,
                text=f"{label}: произведено {production_by_type[label]}, отправлено {demand_by_type[label]}, остаток {stock_by_type[label]} головок",
                anchor="w",
            ).pack(fill="x", padx=10, pady=5)
        if not all_labels:
            ctk.CTkLabel(details, text="Данных о производстве пока нет").pack(pady=30)

        risks_tab = tabs.tab("Риски")
        risks_frame = ctk.CTkScrollableFrame(risks_tab)
        risks_frame.pack(fill="both", expand=True, padx=10, pady=10)
        risks = []
        today = date.today()
        for batch in batches:
            if batch.remaining_heads <= 0:
                continue
            ready, expires = batch_dates(batch)
            days_left = (expires - today).days
            label = f"{batch.cheese_type.base_name} / {batch.cheese_type.product_form}, варка №{batch.batch_index}"
            if days_left < 0:
                risks.append((0, f"ПРОСРОЧЕНО: {label}; остаток {batch.remaining_heads} головок"))
            elif days_left <= 30:
                risks.append((1, f"Высокий риск: {label}; до конца срока {days_left} суток, остаток {batch.remaining_heads}"))
            elif days_left <= 60 and batch.remaining_heads >= batch.initial_heads * 0.7:
                risks.append((2, f"Средний риск: {label}; большой остаток, до конца срока {days_left} суток"))
        for _priority, risk_text in sorted(risks):
            ctk.CTkLabel(risks_frame, text=risk_text, anchor="w", text_color="#FF6B6B").pack(fill="x", padx=10, pady=7)
        if not risks:
            ctk.CTkLabel(risks_frame, text="Опасных партий не обнаружено", text_color="#7CC576").pack(pady=35)

        forecast_tab = tabs.tab("Прогноз")
        forecast_frame = ctk.CTkScrollableFrame(forecast_tab)
        forecast_frame.pack(fill="both", expand=True, padx=10, pady=10)
        order_count = len(completed_orders)
        ctk.CTkLabel(
            forecast_frame,
            text=f"Доступно завершённых заказов: {order_count}",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).pack(anchor="w", padx=10, pady=(10, 5))
        neural_result = train_and_forecast(
            completed_orders, BASE_DIR / "neural_demand_model.json"
        )
        ctk.CTkLabel(
            forecast_frame,
            text=neural_result["message"],
            justify="left",
            text_color="#7CC576" if neural_result["ready"] else "#F2C94C",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(anchor="w", padx=10, pady=8)
        ctk.CTkLabel(
            forecast_frame,
            text=("Модель: многослойный перцептрон 3–8–1. "
                  "Обучение обновляется после каждого завершённого заказа."),
            justify="left",
        ).pack(anchor="w", padx=10, pady=(0, 12))
        for label, forecast_7, forecast_30 in neural_result["forecasts"]:
            ctk.CTkLabel(
                forecast_frame,
                text=(f"{label}: на 7 дней — около {forecast_7} головок; "
                      f"на 30 дней — около {forecast_30} головок"),
                anchor="w",
            ).pack(fill="x", padx=10, pady=6)

        recommendations_tab = tabs.tab("Рекомендации")
        recommendations = ctk.CTkScrollableFrame(recommendations_tab)
        recommendations.pack(fill="both", expand=True, padx=10, pady=10)
        recommendation_texts = []
        if risks:
            recommendation_texts.append("Сначала реализуйте партии из раздела «Риски», начиная с ближайшего срока годности.")
        if demand_by_type:
            leader = max(demand_by_type, key=demand_by_type.get)
            recommendation_texts.append(f"Наиболее востребованный вид: {leader}. Учитывайте его в следующем плане производства.")
            for label, demand in demand_by_type.items():
                if stock_by_type[label] < demand * 0.5:
                    recommendation_texts.append(f"Возможен дефицит {label}: текущий остаток заметно ниже исторического спроса.")
                elif stock_by_type[label] > max(demand * 2, 100):
                    recommendation_texts.append(f"Возможен избыток {label}: временно сократите производство.")
        if written_off_heads > shipped_heads * 0.1 and written_off_heads > 0:
            recommendation_texts.append("Доля списаний повышена. Проверьте причины ручных списаний и условия хранения.")
        if not recommendation_texts:
            recommendation_texts.append("Для подробных рекомендаций необходимо накопить больше производства и завершённых заказов.")
        for index, recommendation in enumerate(recommendation_texts, 1):
            ctk.CTkLabel(
                recommendations, text=f"{index}. {recommendation}", justify="left", anchor="w", wraplength=880
            ).pack(fill="x", padx=10, pady=8)

    def open_edit_batch(self, batch_id):
        with SessionLocal() as session:
            batch = session.scalar(
                select(Batch).where(Batch.id == batch_id).options(joinedload(Batch.cheese_type))
            )
            if batch is None:
                messagebox.showerror("Ошибка", "Варка не найдена")
                return
            current = {
                "name": batch.cheese_type.base_name,
                "kind": batch.cheese_type.product_form,
                "basis": str(batch.cheese_type.diameter_mm),
                "batch_index": batch.batch_index,
                "date": batch.production_date.isoformat(),
                "heads": batch.remaining_heads,
                "weight": batch.remaining_weight,
                "cheese_type_id": batch.cheese_type_id,
            }

        window = ctk.CTkToplevel(self)
        window.title("Изменение сыра")
        window.geometry("500x720")
        window.transient(self)
        apply_dark_titlebar(window)
        heading(window, "Изменение сыра")
        name = field(window, "Название")
        name.insert(0, current["name"])
        ctk.CTkLabel(window, text="Вид сыра").pack(anchor="w", padx=20)
        cheese_kind = ctk.CTkOptionMenu(
            window, values=["280", "380", "Блок", "Фасовка", "Сегмент"]
        )
        cheese_kind.set(current["kind"])
        cheese_kind.pack(fill="x", padx=20, pady=(3, 10))
        ctk.CTkLabel(window, text="Параметры по размеру").pack(anchor="w", padx=20)
        parameter_basis = ctk.CTkOptionMenu(window, values=["280", "380"])
        parameter_basis.set(current["basis"])
        parameter_basis.pack(fill="x", padx=20, pady=(3, 10))
        ctk.CTkLabel(
            window, text=f"Номер варки: {current['batch_index']}"
        ).pack(anchor="w", padx=20, pady=(2, 10))
        produced = field(window, "Дата варки (ГГГГ-ММ-ДД)")
        produced.insert(0, current["date"])
        heads = field(window, "Текущий остаток головок")
        heads.insert(0, str(current["heads"]))
        weight = field(window, "Текущий остаток веса, кг")
        weight.insert(0, f"{current['weight']:.2f}")
        maturity_label = ctk.CTkLabel(window, text="")
        maturity_label.pack(anchor="w", padx=20, pady=4)
        shelf_label = ctk.CTkLabel(window, text="")
        shelf_label.pack(anchor="w", padx=20, pady=4)

        parameters = {
            "280": {"heads": 208, "maturation": 30, "shelf": 120},
            "380": {"heads": 150, "maturation": 60, "shelf": 240},
        }

        def update_parameters(_selected=None):
            kind = cheese_kind.get()
            if kind in ("280", "380"):
                parameter_basis.configure(state="normal")
                parameter_basis.set(kind)
                parameter_basis.configure(state="disabled")
            else:
                parameter_basis.configure(state="normal")
            values = parameters[parameter_basis.get()]
            shelf_days = values["shelf"] - 50 if kind == "Блок" else values["shelf"]
            maturity_label.configure(text=f"Срок созревания: {values['maturation']} суток")
            shelf_label.configure(text=f"Срок годности: {shelf_days} суток")

        cheese_kind.configure(command=update_parameters)
        parameter_basis.configure(command=update_parameters)
        update_parameters()

        def save_changes():
            try:
                base_name = name.get().strip()
                if not base_name:
                    raise ValueError("Введите название сыра")
                kind = cheese_kind.get()
                basis = int(parameter_basis.get())
                production_date = datetime.strptime(produced.get().strip(), "%Y-%m-%d").date()
                remaining_heads = int(heads.get())
                remaining_weight = float(weight.get().replace(",", "."))
                if remaining_heads < 0 or remaining_weight < 0:
                    raise ValueError("Остаток и вес не могут быть отрицательными")
                if remaining_heads == 0:
                    remaining_weight = 0.0
                values = parameters[str(basis)]
                shelf_days = values["shelf"] - 50 if kind == "Блок" else values["shelf"]

                with SessionLocal() as session:
                    db_batch = session.get(Batch, batch_id)
                    target_type = session.scalar(select(CheeseType).where(
                        CheeseType.base_name == base_name,
                        CheeseType.product_form == kind,
                        CheeseType.diameter_mm == basis,
                    ))
                    if target_type is None:
                        target_type = CheeseType(
                            name=f"{base_name}::{kind}::{basis}",
                            base_name=base_name,
                            diameter_mm=basis,
                            heads_per_batch=values["heads"],
                            average_head_weight=(remaining_weight / remaining_heads) if remaining_heads else 0.0,
                            maturation_days=values["maturation"],
                            shelf_life_days=shelf_days,
                            product_form=kind,
                        )
                        session.add(target_type)
                        session.flush()
                    if db_batch.cheese_type_id != target_type.id:
                        last_index = session.scalar(
                            select(func.max(Batch.batch_index)).where(
                                Batch.cheese_type_id == target_type.id
                            )
                        ) or 0
                        db_batch.batch_index = last_index + 1
                        db_batch.batch_number = f"{target_type.id}:{db_batch.batch_index}"
                        db_batch.cheese_type_id = target_type.id
                    db_batch.production_date = production_date
                    db_batch.remaining_heads = remaining_heads
                    db_batch.remaining_weight = remaining_weight
                    db_batch.initial_heads = max(db_batch.initial_heads, remaining_heads)
                    db_batch.initial_weight = max(db_batch.initial_weight, remaining_weight)
                    session.commit()
                messagebox.showinfo("Готово", "Данные сыра изменены")
                window.destroy()
                self.show_maker()
            except IntegrityError:
                messagebox.showerror("Ошибка", "Такой вариант сыра уже существует")
            except ValueError as error:
                if "time data" in str(error):
                    messagebox.showerror("Ошибка", "Введите дату в формате ГГГГ-ММ-ДД")
                else:
                    messagebox.showerror("Ошибка", str(error))

        ctk.CTkButton(
            window, text="Сохранить изменения", height=44, command=save_changes
        ).pack(fill="x", padx=20, pady=16)

    def open_write_off(self, batch_id):
        with SessionLocal() as session:
            batch = session.scalar(
                select(Batch).where(Batch.id == batch_id).options(joinedload(Batch.cheese_type))
            )
            if batch is None:
                messagebox.showerror("Ошибка", "Варка не найдена")
                return
            info = (
                batch.batch_index,
                batch.cheese_type.base_name,
                batch.remaining_heads,
                batch.remaining_weight,
            )

        window = ctk.CTkToplevel(self)
        window.title("Ручное списание")
        window.geometry("440x430")
        window.transient(self)
        apply_dark_titlebar(window)
        heading(window, "Списание со склада")
        ctk.CTkLabel(
            window,
            text=f"Варка №{info[0]} — {info[1]}\nДоступно: {info[2]} головок, {info[3]:.2f} кг",
        ).pack(pady=8)
        quantity = field(window, "Списать головок")
        reason = field(window, "Причина", "Например: повреждение упаковки")

        def save_write_off():
            try:
                amount = int(quantity.get())
                if amount <= 0:
                    raise ValueError("Количество должно быть больше нуля")
                with SessionLocal() as session:
                    db_batch = session.get(Batch, batch_id)
                    if db_batch is None or amount > db_batch.remaining_heads:
                        raise ValueError("Нельзя списать больше доступного остатка")
                    average_weight = db_batch.remaining_weight / db_batch.remaining_heads
                    removed_weight = min(db_batch.remaining_weight, average_weight * amount)
                    db_batch.remaining_heads -= amount
                    db_batch.remaining_weight -= removed_weight
                    session.add(WriteOff(
                        batch_id=batch_id,
                        quantity_heads=amount,
                        weight_kg=removed_weight,
                        reason=reason.get().strip() or "Ручное списание",
                    ))
                    session.commit()
                messagebox.showinfo("Готово", f"Списано {amount} головок")
                window.destroy()
                self.show_maker()
            except ValueError as error:
                messagebox.showerror("Ошибка", str(error))

        ctk.CTkButton(
            window, text="Подтвердить списание", height=42, command=save_write_off
        ).pack(fill="x", padx=20, pady=18)

    def open_add_cheese(self):
        window = ctk.CTkToplevel(self)
        window.title("Добавление сыра")
        center_window(window, 470, 750)
        window.transient(self)
        apply_dark_titlebar(window)
        heading(window, "Добавление сыра")
        name = field(window, "Название", "Например: Российский")
        ctk.CTkLabel(window, text="Вид сыра").pack(anchor="w", padx=20)
        cheese_kind = ctk.CTkOptionMenu(
            window, values=["280", "380", "Блок", "Фасовка", "Сегмент"]
        )
        cheese_kind.pack(fill="x", padx=20, pady=(3, 10))
        ctk.CTkLabel(
            window, text="Параметры по размеру (для блока, фасовки и сегмента)"
        ).pack(anchor="w", padx=20)
        parameter_basis = ctk.CTkOptionMenu(window, values=["280", "380"])
        parameter_basis.pack(fill="x", padx=20, pady=(3, 10))
        number = field(window, "Номер варки")
        number.insert(0, "Назначается автоматически")
        number.configure(state="disabled")
        produced = field(window, "Дата варки (ГГГГ-ММ-ДД)")
        produced.insert(0, date.today().isoformat())
        heads = field(window, "Количество головок")
        maturation = field(window, "Срок созревания, суток")
        shelf = field(window, "Срок годности, суток")
        total_weight = field(window, "Общий фактический вес, кг", "Например: 1924.5")

        parameters = {
            "280": {"heads": 208, "maturation": 30, "shelf": 120},
            "380": {"heads": 150, "maturation": 60, "shelf": 240},
        }

        def fill_automatic_fields(_selected=None):
            selected_kind = cheese_kind.get()
            if selected_kind in ("280", "380"):
                parameter_basis.configure(state="normal")
                parameter_basis.set(selected_kind)
                parameter_basis.configure(state="disabled")
            else:
                parameter_basis.configure(state="normal")
            values = parameters[parameter_basis.get()]
            shelf_days = values["shelf"] - 50 if selected_kind == "Блок" else values["shelf"]
            for entry, value in (
                (heads, values["heads"]),
                (maturation, values["maturation"]),
                (shelf, shelf_days),
            ):
                entry.configure(state="normal")
                entry.delete(0, "end")
                entry.insert(0, str(value))
                entry.configure(state="disabled")

        cheese_kind.configure(command=fill_automatic_fields)
        parameter_basis.configure(command=fill_automatic_fields)
        fill_automatic_fields()

        def save():
            try:
                cheese_name = name.get().strip()
                if not cheese_name:
                    raise ValueError("Введите название сыра")
                selected_kind = cheese_kind.get()
                d = int(parameter_basis.get())
                values = parameters[str(d)]
                shelf_days = values["shelf"] - 50 if selected_kind == "Блок" else values["shelf"]
                production_date = datetime.strptime(
                    produced.get().strip(), "%Y-%m-%d"
                ).date()
                head_count = values["heads"]
                kg = float(total_weight.get().replace(",", "."))
                if kg <= 0:
                    raise ValueError("Общий вес должен быть больше нуля")

                with SessionLocal() as session:
                    cheese = session.scalar(
                        select(CheeseType).where(
                            CheeseType.base_name == cheese_name,
                            CheeseType.product_form == selected_kind,
                            CheeseType.diameter_mm == d,
                        )
                    )
                    if cheese is None:
                        cheese = CheeseType(
                            name=f"{cheese_name}::{selected_kind}::{d}",
                            base_name=cheese_name,
                            diameter_mm=d,
                            heads_per_batch=head_count,
                            average_head_weight=kg / head_count,
                            maturation_days=values["maturation"],
                            shelf_life_days=shelf_days,
                            product_form=selected_kind,
                        )
                        session.add(cheese)
                        session.flush()
                    else:
                        cheese.heads_per_batch = head_count
                        cheese.maturation_days = values["maturation"]
                        cheese.shelf_life_days = shelf_days
                        cheese.product_form = selected_kind
                        cheese.average_head_weight = kg / head_count
                    last_batch_index = session.scalar(
                        select(func.max(Batch.batch_index)).where(
                            Batch.cheese_type_id == cheese.id
                        )
                    ) or 0
                    new_batch_index = last_batch_index + 1
                    session.add(Batch(
                        batch_number=f"{cheese.id}:{new_batch_index}",
                        batch_index=new_batch_index,
                        cheese_type_id=cheese.id,
                        production_date=production_date,
                        initial_heads=head_count,
                        remaining_heads=head_count,
                        initial_weight=kg,
                        remaining_weight=kg,
                    ))
                    session.commit()
                messagebox.showinfo(
                    "Готово", f"Сыр добавлен. Номер варки: {new_batch_index}"
                )
                window.destroy()
                self.show_maker()
            except IntegrityError:
                messagebox.showerror("Ошибка", "Не удалось создать новую варку")
            except ValueError as error:
                if "time data" in str(error):
                    messagebox.showerror("Ошибка", "Введите дату в формате ГГГГ-ММ-ДД")
                else:
                    messagebox.showerror("Ошибка", str(error))

        ctk.CTkButton(
            window,
            text="Добавить сыр",
            height=42,
            fg_color=SWAMP_COLOR,
            hover_color=SWAMP_HOVER,
            command=save,
        ).pack(fill="x", padx=20, pady=14)

    def open_orders(self):
        window = ctk.CTkToplevel(self)
        window.title("Заказы покупателей")
        center_window(window, 1000, 650)
        window.transient(self)
        apply_dark_titlebar(window)
        heading(window, "Заказы покупателей")
        body = ctk.CTkScrollableFrame(window)
        body.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        with SessionLocal() as session:
            orders = list(session.scalars(
                select(Order).options(joinedload(Order.items).joinedload(OrderItem.cheese_type)).order_by(Order.created_at.desc())
            ).unique())
            rows = []
            for order in orders:
                item = order.items[0]
                cheese_label = f"{item.cheese_type.base_name} / {item.cheese_type.product_form}"
                rows.append((order.id, order.customer_name, order.phone, cheese_label, item.quantity_heads, order.status, order.created_at))

        for order_id, customer, phone, cheese, quantity, status, created in rows:
            card = ctk.CTkFrame(body)
            card.pack(fill="x", pady=5)
            ctk.CTkLabel(
                card,
                text=f"Заказ №{order_id} от {created:%d.%m.%Y %H:%M}\n{customer} | Телефон: {phone or 'не указан'}\n{cheese}, {quantity} головок\nСтатус: {status}",
                justify="left", anchor="w"
            ).pack(side="left", fill="x", expand=True, padx=15, pady=12)
            if status == ORDER_WAITING:
                ctk.CTkButton(
                    card, text="Обработать", width=130,
                    command=lambda oid=order_id, w=window: self.open_order_processing(oid, w)
                ).pack(side="right", padx=12)
            elif status == "Принят":
                ctk.CTkButton(
                    card, text="Удалить", width=110, fg_color="#b91c1c",
                    command=lambda oid=order_id, w=window: self.delete_accepted_order(oid, w, True)
                ).pack(side="right", padx=12)
        if not rows:
            ctk.CTkLabel(body, text="Заказов пока нет").pack(pady=40)

    def open_order_processing(self, order_id, orders_window):
        with SessionLocal() as session:
            order = session.scalar(
                select(Order).where(Order.id == order_id).options(
                    joinedload(Order.items).joinedload(OrderItem.cheese_type)
                )
            )
            item = order.items[0]
            cheese_label = f"{item.cheese_type.base_name} / {item.cheese_type.product_form}"
            order_info = (order.customer_name, cheese_label, item.quantity_heads, item.cheese_type_id)
            batches = list(session.scalars(
                select(Batch).where(Batch.cheese_type_id == item.cheese_type_id)
                .options(joinedload(Batch.cheese_type)).order_by(Batch.production_date)
            ).unique())

        suitable = []
        today = date.today()
        for batch in batches:
            ready, expires = batch_dates(batch)
            if ready <= today <= expires and batch.remaining_heads > 0:
                suitable.append({
                    "id": batch.id,
                    "number": batch.batch_index,
                    "available": batch.remaining_heads,
                    "expires": expires,
                    "avg_weight": batch.remaining_weight / batch.remaining_heads,
                })
        suitable.sort(key=lambda x: x["expires"])

        window = ctk.CTkToplevel(self)
        window.title(f"Обработка заказа №{order_id}")
        window.geometry("760x640")
        window.transient(self)
        apply_dark_titlebar(window)
        heading(window, f"Заказ №{order_id}")
        ctk.CTkLabel(
            window,
            text=f"Заказчик: {order_info[0]}\nСыр: {order_info[1]}\nТребуется: {order_info[2]} головок",
            justify="left",
        ).pack(pady=5)
        ctk.CTkLabel(window, text="Укажите количество из каждой партии:", font=ctk.CTkFont(weight="bold")).pack(pady=(15, 5))
        body = ctk.CTkScrollableFrame(window, height=280)
        body.pack(fill="both", expand=True, padx=20, pady=5)
        allocation_entries = {}
        for batch in suitable:
            row = ctk.CTkFrame(body)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(
                row,
                text=f'Варка №{batch["number"]} | доступно {batch["available"]} | годен до {batch["expires"]:%d.%m.%Y}',
                anchor="w",
            ).pack(side="left", fill="x", expand=True, padx=10, pady=10)
            entry = ctk.CTkEntry(row, width=100, placeholder_text="0")
            entry.pack(side="right", padx=10)
            allocation_entries[batch["id"]] = entry

        def recommend():
            remaining = order_info[2]
            for batch in suitable:
                amount = min(remaining, batch["available"])
                entry = allocation_entries[batch["id"]]
                entry.delete(0, "end")
                entry.insert(0, str(amount if amount > 0 else 0))
                remaining -= amount
            if remaining > 0:
                messagebox.showwarning("Недостаточно сыра", f"Не хватает {remaining} головок готового сыра")

        def confirm():
            try:
                allocations = []
                total = 0
                by_id = {x["id"]: x for x in suitable}
                for batch_id, entry in allocation_entries.items():
                    text = entry.get().strip() or "0"
                    amount = int(text)
                    if amount < 0 or amount > by_id[batch_id]["available"]:
                        raise ValueError(f'Неверное количество для варки №{by_id[batch_id]["number"]}')
                    if amount:
                        allocations.append((batch_id, amount, by_id[batch_id]["avg_weight"]))
                        total += amount
                if total != order_info[2]:
                    raise ValueError(f"Выбрано {total}, а требуется {order_info[2]} головок")
                with SessionLocal() as session:
                    db_order = session.get(Order, order_id)
                    if db_order.status != ORDER_WAITING:
                        raise ValueError("Заказ уже обработан")
                    for batch_id, amount, avg_weight in allocations:
                        db_batch = session.get(Batch, batch_id)
                        weight = min(db_batch.remaining_weight, amount * avg_weight)
                        db_batch.remaining_heads -= amount
                        db_batch.remaining_weight -= weight
                        session.add(Shipment(
                            order_id=order_id,
                            batch_id=batch_id,
                            quantity_heads=amount,
                            weight_kg=weight,
                        ))
                    db_order.status = "Отправлен"
                    session.commit()
                messagebox.showinfo("Готово", "Отгрузка подтверждена, остатки обновлены")
                window.destroy()
                orders_window.destroy()
                self.open_orders()
                self.show_maker()
            except ValueError as error:
                messagebox.showerror("Ошибка", str(error))

        def reject():
            with SessionLocal() as session:
                db_order = session.get(Order, order_id)
                db_order.status = "Отклонён"
                session.commit()
            window.destroy()
            orders_window.destroy()
            self.open_orders()

        buttons = ctk.CTkFrame(window, fg_color="transparent")
        buttons.pack(fill="x", padx=20, pady=12)
        ctk.CTkButton(buttons, text="Предложить лучший вариант", command=recommend).pack(side="left", padx=5)
        ctk.CTkButton(buttons, text="Подтвердить отправку", command=confirm).pack(side="left", padx=5)
        ctk.CTkButton(buttons, text="Отклонить", fg_color="#b91c1c", command=reject).pack(side="right", padx=5)
        if suitable:
            recommend()
        else:
            ctk.CTkLabel(body, text="Нет созревших и непросроченных партий этого сыра").pack(pady=30)

    def show_customer(self):
        clear_window(self)
        self.resizable(True, True)
        self.geometry("1180x720")
        heading(self, "Каталог продукции")
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=20, pady=(0, 10))
        search = ctk.CTkEntry(
            top,
            height=46,
            font=ctk.CTkFont(size=16),
            placeholder_text="Поиск по названию сыра",
        )
        search.pack(side="left", fill="x", expand=True, padx=10, pady=12)
        body = ctk.CTkScrollableFrame(self)
        body.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        def render(_event=None):
            for widget in body.winfo_children():
                widget.destroy()
            query = search.get().strip().lower()
            with SessionLocal() as session:
                cheeses = list(session.scalars(select(CheeseType).order_by(CheeseType.base_name)))
                cards = []
                for cheese in cheeses:
                    if query and query not in cheese.base_name.lower():
                        continue
                    batches = list(session.scalars(
                        select(Batch).where(Batch.cheese_type_id == cheese.id).options(joinedload(Batch.cheese_type))
                    ).unique())
                    available = sum(x.remaining_heads for x in batches if batch_status(x) in ("Готова к продаже", "Реализовать первой"))
                    if available > 0:
                        cards.append((cheese.id, cheese.base_name, cheese.product_form, available))
            for cheese_id, name, product_form, available in cards:
                card = ctk.CTkFrame(body)
                card.pack(fill="x", pady=5)
                ctk.CTkLabel(
                    card,
                    text=f"{name} | {product_form} | готово к заказу: {available} головок",
                    anchor="w",
                ).pack(side="left", fill="x", expand=True, padx=15, pady=14)
                ctk.CTkButton(
                    card, text="Заказать", state="normal" if available else "disabled",
                    command=lambda cid=cheese_id: self.open_create_order(cid)
                ).pack(side="right", padx=12)
            if not cards:
                ctk.CTkLabel(body, text="Ничего не найдено").pack(pady=30)

        search.bind("<KeyRelease>", render)
        orders_holder = ctk.CTkFrame(
            top, fg_color="transparent"
        )
        orders_holder.pack(side="left", padx=7)
        customer_orders_button = ctk.CTkButton(
            orders_holder,
            text="Мои заказы",
            width=160,
            height=46,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self.open_customer_orders,
        )
        customer_orders_button.pack(side="left")
        ctk.CTkButton(
            top,
            text="Главное меню",
            width=160,
            height=46,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self.show_main_menu,
        ).pack(side="left", padx=(7, 10))
        render()

    def open_create_order(self, cheese_id):
        with SessionLocal() as session:
            cheese = session.get(CheeseType, cheese_id)
            cheese_name = cheese.base_name
            cheese_kind = cheese.product_form
        window = ctk.CTkToplevel(self)
        window.title("Создание заказа")
        center_window(window, 450, 540)
        window.transient(self)
        apply_dark_titlebar(window)
        heading(window, "Новый заказ")
        ctk.CTkLabel(
            window, text=f"Сыр: {cheese_name} | Вид: {cheese_kind}"
        ).pack(pady=5)
        customer = field(window, "Имя заказчика или организация")
        phone = field(window, "Номер телефона для связи", "+375 (__) ___-__-__")
        quantity = field(window, "Количество головок")
        comment = field(window, "Комментарий (необязательно)")

        def create():
            try:
                customer_name = customer.get().strip()
                phone_number = phone.get().strip()
                amount = int(quantity.get())
                if not customer_name or not phone_number or amount <= 0:
                    raise ValueError
                with SessionLocal() as session:
                    order = Order(
                        customer_name=customer_name,
                        phone=phone_number,
                        comment=comment.get().strip(),
                    )
                    order.items.append(OrderItem(cheese_type_id=cheese_id, quantity_heads=amount))
                    session.add(order)
                    session.commit()
                    order_id = order.id
                messagebox.showinfo("Заказ создан", f"Заказ №{order_id} отправлен сыроделу")
                window.destroy()
                self.show_customer()
            except ValueError:
                messagebox.showerror(
                    "Ошибка", "Введите имя, номер телефона и правильное количество"
                )

        ctk.CTkButton(
            window,
            text="Отправить заказ",
            height=42,
            fg_color=SWAMP_COLOR,
            hover_color=SWAMP_HOVER,
            command=create,
        ).pack(fill="x", padx=20, pady=18)

    def open_customer_orders(self):
        window = ctk.CTkToplevel(self)
        window.title("Список заказов")
        center_window(window, 820, 590)
        window.transient(self)
        apply_dark_titlebar(window)
        heading(window, "Список заказов")
        body = ctk.CTkScrollableFrame(window)
        body.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        with SessionLocal() as session:
            orders = list(session.scalars(
                select(Order).options(joinedload(Order.items).joinedload(OrderItem.cheese_type)).order_by(Order.created_at.desc())
            ).unique())
            rows = [(
                x.id,
                x.customer_name,
                f"{x.items[0].cheese_type.base_name} / {x.items[0].cheese_type.product_form}",
                x.items[0].quantity_heads,
                x.status,
            ) for x in orders]
        for order_id, customer, cheese, amount, status in rows:
            card = ctk.CTkFrame(body)
            card.pack(fill="x", pady=5)
            ctk.CTkLabel(
                card,
                text=f"Заказ №{order_id} | {customer} | {cheese} — {amount} головок | {status}",
                anchor="w",
            ).pack(side="left", fill="x", expand=True, padx=10, pady=10)
            if status == "Отправлен":
                ctk.CTkButton(
                    card, text="Заказ получен", width=135,
                    command=lambda oid=order_id, w=window: self.accept_order(oid, w)
                ).pack(side="right", padx=8)
            elif status == "Принят":
                ctk.CTkButton(
                    card, text="Удалить", width=100, fg_color="#b91c1c",
                    command=lambda oid=order_id, w=window: self.delete_accepted_order(oid, w, False)
                ).pack(side="right", padx=8)
        if not rows:
            ctk.CTkLabel(body, text="Заказов пока нет").pack(pady=30)

    def accept_order(self, order_id, orders_window):
        with SessionLocal() as session:
            order = session.get(Order, order_id)
            if order is None or order.status != "Отправлен":
                messagebox.showerror("Ошибка", "Этот заказ нельзя подтвердить")
                return
            order.status = "Принят"
            session.commit()
        messagebox.showinfo("Готово", f"Получение заказа №{order_id} подтверждено")
        orders_window.destroy()
        self.open_customer_orders()

    def delete_accepted_order(self, order_id, orders_window, maker_view):
        if not messagebox.askyesno(
            "Удаление заказа", f"Удалить принятый заказ №{order_id} из истории?"
        ):
            return
        with SessionLocal() as session:
            order = session.get(Order, order_id)
            if order is None or order.status != "Принят":
                messagebox.showerror("Ошибка", "Удалять можно только принятые заказы")
                return
            session.execute(delete(Shipment).where(Shipment.order_id == order_id))
            session.delete(order)
            session.commit()
        orders_window.destroy()
        self.open_orders() if maker_view else self.open_customer_orders()


def prepare_database():
    Base.metadata.create_all(bind=engine)
    order_columns = {
        column["name"] for column in inspect(engine).get_columns("orders")
    }
    if "phone" not in order_columns:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE orders "
                "ADD COLUMN phone VARCHAR(40) NOT NULL DEFAULT ''"
            ))
    batch_columns = {
        column["name"] for column in inspect(engine).get_columns("batches")
    }
    if "batch_index" not in batch_columns:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE batches "
                "ADD COLUMN batch_index INTEGER NOT NULL DEFAULT 0"
            ))
            connection.execute(text(
                "WITH numbered AS ("
                "SELECT id, ROW_NUMBER() OVER ("
                "PARTITION BY cheese_type_id ORDER BY production_date, id"
                ") AS position FROM batches"
                ") UPDATE batches SET batch_index = ("
                "SELECT position FROM numbered WHERE numbered.id = batches.id"
                ") WHERE batch_index = 0"
            ))
    cheese_columns = {
        column["name"] for column in inspect(engine).get_columns("cheese_types")
    }
    if "product_form" not in cheese_columns:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE cheese_types "
                "ADD COLUMN product_form VARCHAR(30) NOT NULL DEFAULT 'Круг'"
            ))
    if "base_name" not in cheese_columns:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE cheese_types "
                "ADD COLUMN base_name VARCHAR(100) NOT NULL DEFAULT ''"
            ))
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE cheese_types "
            "SET product_form = CAST(diameter_mm AS TEXT) "
            "WHERE product_form = 'Круг'"
        ))
        connection.execute(text(
            "UPDATE cheese_types SET base_name = name "
            "WHERE base_name = ''"
        ))


if __name__ == "__main__":
    prepare_database()
    app = CheeseApp()
    app.mainloop()
