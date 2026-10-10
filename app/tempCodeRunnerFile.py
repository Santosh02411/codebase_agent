def greets(cls):
    cls.gr="hello"
    return cls
@greets
class app:
    pass
print(app.gr)
print(cls.gr)