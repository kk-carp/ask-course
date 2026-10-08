"""Request-local course boundary for public website turns, copied to parallel workers.

None permits the existing internal tools; an empty set permits no course.
Catalog loaders, fact lookup and retrieval all enforce this boundary before I/O.
"""

from contextvars import ContextVar

course_scope = ContextVar("public_course_scope", default=None)


def permits(course_id):
    allowed = course_scope.get()
    return allowed is None or course_id in allowed


def permits_retrieval(course_id):
    return course_scope.get() is None or bool(course_id and permits(course_id))
