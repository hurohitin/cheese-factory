import json
import math
import random
from collections import defaultdict
from datetime import date
from pathlib import Path


MIN_ORDERS = 1
HIDDEN_NEURONS = 8
EPOCHS = 1800
LEARNING_RATE = 0.025


def _month_number(value):
    return value.year * 12 + value.month - 1


def _month_from_number(value):
    return value // 12, value % 12 + 1


def _week_number(value):
    return value.toordinal() // 7


def _week_features(week_number, first_week, total_weeks):
    angle = 2 * math.pi * (week_number % 52) / 52
    trend = (week_number - first_week) / max(1, total_weeks - 1)
    return [math.sin(angle), math.cos(angle), trend]


def _features(month_number, first_month, total_months):
    _year, month = _month_from_number(month_number)
    angle = 2 * math.pi * (month - 1) / 12
    trend = (month_number - first_month) / max(1, total_months - 1)
    return [math.sin(angle), math.cos(angle), trend]


class TinyMLP:
    """Небольшая нейросеть: 3 входа -> 8 скрытых нейронов -> 1 выход."""

    def __init__(self, seed=42):
        generator = random.Random(seed)
        self.w1 = [
            [generator.uniform(-0.45, 0.45) for _ in range(3)]
            for _ in range(HIDDEN_NEURONS)
        ]
        self.b1 = [0.0] * HIDDEN_NEURONS
        self.w2 = [generator.uniform(-0.45, 0.45) for _ in range(HIDDEN_NEURONS)]
        self.b2 = 0.0

    def predict(self, inputs):
        hidden = [
            math.tanh(sum(weight * value for weight, value in zip(row, inputs)) + bias)
            for row, bias in zip(self.w1, self.b1)
        ]
        output = sum(weight * value for weight, value in zip(self.w2, hidden)) + self.b2
        return max(0.0, output), hidden

    def train(self, samples):
        for _epoch in range(EPOCHS):
            for inputs, target in samples:
                prediction, hidden = self.predict(inputs)
                error = prediction - target
                output_gradient = 0.0 if prediction <= 0 and error > 0 else error
                old_w2 = self.w2[:]
                for index in range(HIDDEN_NEURONS):
                    self.w2[index] -= LEARNING_RATE * output_gradient * hidden[index]
                self.b2 -= LEARNING_RATE * output_gradient
                for hidden_index in range(HIDDEN_NEURONS):
                    hidden_gradient = (
                        output_gradient
                        * old_w2[hidden_index]
                        * (1 - hidden[hidden_index] ** 2)
                    )
                    for input_index in range(3):
                        self.w1[hidden_index][input_index] -= (
                            LEARNING_RATE * hidden_gradient * inputs[input_index]
                        )
                    self.b1[hidden_index] -= LEARNING_RATE * hidden_gradient

    def to_dict(self):
        return {"w1": self.w1, "b1": self.b1, "w2": self.w2, "b2": self.b2}


def train_and_forecast(completed_orders, model_path):
    """Автоматически обучает модели и прогнозирует спрос на 7 и 30 дней."""
    weekly = defaultdict(lambda: defaultdict(int))
    for order in completed_orders:
        week_number = _week_number(order.created_at.date())
        for item in order.items:
            label = f"{item.cheese_type.base_name} / {item.cheese_type.product_form}"
            weekly[label][week_number] += item.quantity_heads

    order_count = len(completed_orders)
    if order_count < MIN_ORDERS or not weekly:
        return {"ready": False, "message": "Нет завершённых заказов для обучения.", "forecasts": []}

    if order_count < 5:
        confidence = "очень низкая"
    elif order_count < 20:
        confidence = "низкая"
    elif order_count < 50:
        confidence = "средняя"
    else:
        confidence = "высокая"

    all_weeks = sorted({week for values in weekly.values() for week in values})
    first_week, last_week = all_weeks[0], all_weeks[-1]
    total_weeks = last_week - first_week + 1
    training_first_week = max(first_week, last_week - 51)

    forecasts = []
    saved_models = {}
    next_week = last_week + 1
    for model_index, (label, values) in enumerate(sorted(weekly.items())):
        week_range = range(training_first_week, last_week + 1)
        targets = [values.get(week, 0) for week in week_range]
        scale = max(1, max(targets))
        samples = [
            (_week_features(week, training_first_week, len(targets)), values.get(week, 0) / scale)
            for week in week_range
        ]
        network = TinyMLP(seed=42 + model_index)
        network.train(samples)
        prediction, _hidden = network.predict(
            _week_features(next_week, training_first_week, len(targets) + 1)
        )
        neural_week = max(0.0, prediction * scale)
        recent_weeks = targets[-4:]
        current_rate = sum(recent_weeks) / max(1, len(recent_weeks))
        # На малой истории стабилизируем нейросетевой результат текущим темпом.
        neural_weight = min(0.8, 0.25 + order_count / 80)
        forecast_7 = round(neural_week * neural_weight + current_rate * (1 - neural_weight))
        forecast_30 = round(forecast_7 * 30 / 7)
        forecasts.append((label, max(0, forecast_7), max(0, forecast_30)))
        saved_models[label] = {
            "scale": scale,
            "first_week": training_first_week,
            "last_week": last_week,
            "network": network.to_dict(),
        }

    Path(model_path).write_text(
        json.dumps(saved_models, ensure_ascii=False), encoding="utf-8"
    )
    forecasts.sort(key=lambda item: item[2], reverse=True)
    return {
        "ready": True,
        "message": (
            f"Нейросеть автоматически обучена на {order_count} заказах. "
            f"Достоверность: {confidence}."
        ),
        "confidence": confidence,
        "forecasts": forecasts,
    }
