"""Envía los modelos del SGR a la base ``sgr`` y el resto a la base propia (``default``)."""


def _es_sgr(model):
    from consulta.models import ModeloSGR
    return isinstance(model, type) and issubclass(model, ModeloSGR)


class RouterSGR:
    def db_for_read(self, model, **hints):
        return 'sgr' if _es_sgr(model) else 'default'

    def db_for_write(self, model, **hints):
        return 'sgr' if _es_sgr(model) else 'default'

    def allow_relation(self, obj1, obj2, **hints):
        return _es_sgr(type(obj1)) == _es_sgr(type(obj2))

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Nunca se migra la base del SGR: su estructura la administra el propio SGR.
        if db == 'sgr':
            return False
        return None
