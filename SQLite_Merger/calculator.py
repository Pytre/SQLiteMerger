import logging
from datetime import datetime

from dateutil.relativedelta import relativedelta
from simpleeval import simple_eval, NameNotDefined, FunctionNotDefined


class Calculator:
    """Évaluateur d'expressions"""

    def __init__(self):
        self.functions = {
            "format_date": self._format_date,
            "now": self._now,
            "day": self._day,
            "month": self._month,
            "year": self._year,
            "offset_day": self._offset_day,
            "offset_month": self._offset_month,
            "start_of_month": self._start_of_month,
            "end_of_month": self._end_of_month,
        }

    def evaluate(self, expression: str) -> str:
        """Évalue une expression de manière sécurisée"""
        if not expression or not expression.strip():
            return ""
        if not expression.startswith("="):
            return expression

        try:
            calc_expr = expression[1:]
            result = simple_eval(calc_expr, functions=self.functions, names={})
            return str(result)
        except NameNotDefined as e:
            logging.warning(f"Expression '{calc_expr}' contient un nom non défini : {e}")
            return ""
        except SyntaxError as e:
            logging.warning(f"Erreur de syntaxe dans '{calc_expr}': {e}")
            return ""
        except FunctionNotDefined as e:
            logging.error(
                f"Fonction non autorisée dans l'expression '{calc_expr}': {e}.\n"
                f"Fonctions disponibles: {list(self.functions.keys())}"
            )
        except Exception as e:
            logging.error(f"Erreur lors de l'évaluation de '{expression}': {e}")

    @staticmethod
    def _format_date(date: datetime, fmt: str) -> str:
        """Formate une date"""
        return date.strftime(fmt)

    @staticmethod
    def _day(date: datetime | None = None) -> int:
        """Retourne le jour"""
        if date is None:
            date = datetime.now()
        return date.day

    @staticmethod
    def _month(date: datetime | None = None) -> int:
        """Retourne le mois"""
        if date is None:
            date = datetime.now()
        return date.month

    @staticmethod
    def _year(date: datetime | None = None) -> int:
        """Retourne l'année"""
        if date is None:
            date = datetime.now()
        return date.year

    @staticmethod
    def _now() -> datetime:
        """Retourne la date actuelle"""
        return datetime.now()

    @staticmethod
    def _offset_day(date: datetime | None = None, offset: int = 0) -> datetime:
        """Retourne une date (date du jour si non défini) avec un offset de jour"""
        if date is None:
            date = datetime.now()
        return date + relativedelta(days=offset)

    @staticmethod
    def _offset_month(date: datetime | None = None, offset: int = 0) -> datetime:
        """Retourne une date (date du jour si non défini) avec un offset de mois"""
        if date is None:
            date = datetime.now()
        return date + relativedelta(months=offset)

    @staticmethod
    def _start_of_month(date: datetime | None = None, offset: int = 0) -> datetime:
        """Retourne le début du mois et le décale"""
        if date is None:
            date = datetime.now()
        return date + relativedelta(day=1, months=offset)

    @staticmethod
    def _end_of_month(date: datetime | None = None, offset: int = 0) -> datetime:
        """Retourne la fin du mois et le décale"""
        if date is None:
            date = datetime.now()
        return date + relativedelta(day=1, months=offset + 1, days=-1)


if __name__ == "__main__":
    calc = Calculator()
    expr = "=format_date(offset_day(now(), -28), '%Y.%m')"
    result = calc.evaluate(expr)
    print(result)
