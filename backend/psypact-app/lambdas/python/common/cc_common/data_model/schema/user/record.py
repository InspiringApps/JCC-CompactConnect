"""Re-export the shared user record so this package and the shared class are the same object."""

from common_lambdas.data_model.schema.user.record import UserRecordSchema

__all__ = ['UserRecordSchema']
