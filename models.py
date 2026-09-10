from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class CheeseType(Base):
    __tablename__ = "cheese_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    base_name: Mapped[str] = mapped_column(String(100), nullable=False)
    diameter_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    heads_per_batch: Mapped[int] = mapped_column(Integer, nullable=False)
    average_head_weight: Mapped[float] = mapped_column(Float, nullable=False)
    maturation_days: Mapped[int] = mapped_column(Integer, nullable=False)
    shelf_life_days: Mapped[int] = mapped_column(Integer, nullable=False)
    product_form: Mapped[str] = mapped_column(String(30), default="Круг", nullable=False)

    batches: Mapped[list["Batch"]] = relationship(back_populates="cheese_type")
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="cheese_type")


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False)
    cheese_type_id: Mapped[int] = mapped_column(ForeignKey("cheese_types.id"), nullable=False)
    production_date: Mapped[date] = mapped_column(Date, nullable=False)
    initial_heads: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_heads: Mapped[int] = mapped_column(Integer, nullable=False)
    initial_weight: Mapped[float] = mapped_column(Float, nullable=False)
    remaining_weight: Mapped[float] = mapped_column(Float, nullable=False)

    cheese_type: Mapped["CheeseType"] = relationship(back_populates="batches")
    shipments: Mapped[list["Shipment"]] = relationship(back_populates="batch")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="Ожидает подтверждения", nullable=False)
    comment: Mapped[str] = mapped_column(String(500), default="", nullable=False)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    shipments: Mapped[list["Shipment"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    cheese_type_id: Mapped[int] = mapped_column(ForeignKey("cheese_types.id"), nullable=False)
    quantity_heads: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped["Order"] = relationship(back_populates="items")
    cheese_type: Mapped["CheeseType"] = relationship(back_populates="order_items")


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), nullable=False)
    quantity_heads: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    shipped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    order: Mapped["Order"] = relationship(back_populates="shipments")
    batch: Mapped["Batch"] = relationship(back_populates="shipments")


class WriteOff(Base):
    __tablename__ = "write_offs"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), nullable=False)
    quantity_heads: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String(300), default="Ручное списание", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
