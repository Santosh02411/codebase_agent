import pytest

from app.intel import extract as ex
from app.intel.extract import extract_file
from app.intel.ts_core import available_grammars

pytestmark = pytest.mark.skipif(not all(available_grammars().values()), reason="tree-sitter grammars not installed")


def facts(path, src):
    return extract_file(path, src.encode())


def by(f):
    return {s.qualname: s for s in f.symbols}


def test_python_ast_symbols_routes_models_tests():
    f = facts("pkg/mod.py", '''"""mod doc"""
import os, json as j
from .utils import helper as h, other
from . import sibling
from fastapi import APIRouter
router = APIRouter(prefix="/api")
MAX = 3
# TODO: tidy
class Base: pass
class User(Base):
    """A user."""
    __tablename__ = "users"
    id = Column(Integer)
    def save(self, x: int) -> bool:
        self.validate(x); return h(x)
@router.get("/users/{id}")
async def get_user(id):
    """fetch"""
    return User().save(id)
''')
    s = by(f)
    assert f.parser == "python-ast" and f.module_doc == "mod doc"
    assert s["User"].bases == ["Base"] and "model" in s["User"].tags and s["User"].doc == "A user."
    assert s["User.save"].kind == "method" and s["User.save"].calls == ["self.validate", "h"]
    assert s["User.save"].signature == "def save(self, x: int) -> bool"
    assert s["get_user"].route == "GET /api/users/{id}" and "async" in s["get_user"].tags
    assert "router.get" not in s["get_user"].calls          # decorators are not calls made by the function
    assert s["MAX"].kind == "constant" and s["router"].kind == "variable"
    assert [(i.module, i.level) for i in f.imports] == [("os", 0), ("json", 0), ("utils", 1), ("", 1), ("fastapi", 0)]
    assert f.todos == [{"line": 8, "text": "TODO: tidy"}]
    assert f.apis[0].path == "/api/users/{id}"


def test_python_model_detection_avoids_false_positives():
    f = facts("m.py", """from sqlalchemy.orm import DeclarativeBase
class Base(DeclarativeBase): pass
class Plain(Base):
    def helper(self): pass
class Row(Base):
    __tablename__ = "rows"
    id = Column(Integer)
class Schema(BaseModel):
    name: str
class Thing(SQLModel):
    name: str
""")
    tags = {s.qualname: "model" in s.tags for s in f.symbols if s.kind == "class"}
    assert tags == {"Base": False, "Plain": False, "Row": True, "Schema": False, "Thing": False}


def test_python_syntax_error_falls_back_to_tree_sitter():
    f = facts("bad.py", "def (:\n  pass\ndef ok(x):\n    return g(x)\nclass A(B):\n    def m(self): self.n()\nimport os\n")
    s = by(f)
    assert f.parser == "tree-sitter:python" and any("syntax" in e for e in f.errors)
    assert s["ok"].calls == ["g"] and s["A"].bases == ["B"] and s["A.m"].calls == ["self.n"]


def test_javascript_functions_classes_imports_routes_tests():
    f = facts("src/a.js", '''import React, {useState as us} from "react";
import * as u from "./u";
const x = require("./x");
/** Greeter class. */
export default class A extends B {
  @Get("/z") foo(a) { return bar(a); }
  handler = () => baz();
}
export const f = async (a) => { helper(a); }; // TODO: x
const MAX = 3;
app.get("/users", (req, res) => { res.send(u.render()); });
router.post("/items", createItem);
axios.get("/not-a-route", cfg);
describe("s", () => { it("works", () => {}); });
''')
    s = by(f)
    assert s["A"].bases == ["B"] and s["A"].doc == "Greeter class." and s["A"].exported
    assert s["A.foo"].route == "GET /z" and s["A.handler"].kind == "method"
    assert s["f"].kind == "function" and "async" in s["f"].tags and s["f"].calls == ["helper"]
    assert s["MAX"].kind == "constant"
    assert s["GET /users"].calls == ["res.send", "u.render"] and "inline" in s["GET /users"].tags
    assert {(a.method, a.path, a.handler) for a in f.apis} >= {("GET", "/users", "GET /users"), ("POST", "/items", "createItem")}
    assert not any(a.path == "/not-a-route" for a in f.apis)           # HTTP *clients* are not API routes
    mods = {i.module: i for i in f.imports}
    assert mods["react"].names == [["default", "React"], ["useState", "us"]] and mods["./u"].alias == "u" and mods["./x"].kind == "require"
    assert f.tests == [{"name": "works", "line": 14}] and f.is_test


def test_typescript_interfaces_enums_types_nest_and_models():
    f = facts("src/c.ts", '''@Controller("cats")
export class CatsController extends Base implements IFoo, IBar {
  @Get(":id") find(id: string): Cat { return this.svc.find(id); }
}
@Entity() export class Cat { name: string; }
export interface Repo<T> extends Base { get(id: string): T }
type Id = string;
enum Color { Red }
''')
    s = by(f)
    assert s["CatsController"].bases == ["Base", "IFoo", "IBar"]
    assert s["CatsController.find"].route == "GET /cats/:id" and f.apis[0].framework == "nestjs"
    assert s["Cat"].tags == ["model"] and s["Repo"].kind == "interface" and s["Repo"].bases == ["Base"]
    assert s["Id"].kind == "type" and s["Color"].kind == "enum"


def test_tsx_parses_jsx():
    f = facts("src/App.tsx", 'import X from "./x";\nexport function App() { return <div><X/></div>; }\n')
    assert by(f)["App"].kind == "function" and f.parser == "tree-sitter:tsx"


def test_java_spring_jpa_junit():
    f = facts("src/App.java", '''package com.x.y;
import java.util.List;
import com.x.z.*;
/** Users API */
@RestController @RequestMapping("/api")
public class A extends B implements C, D<E> {
  private static final int MAX = 3;
  @GetMapping("/u") public List<U> list(int a) { return svc.find(a); }
  @PostMapping(value="/v") public void make() { new Foo(); }
  @Test void t() {}
}
interface I extends J { void q(); }
@Entity class Pet { int id; }
enum E { X, Y }
''')
    s = by(f)
    assert f.package == "com.x.y"
    assert s["A"].bases == ["B", "C", "D"] and s["A"].doc == "Users API"
    assert s["A.MAX"].kind == "constant"
    assert s["A.list"].route == "GET /api/u" and s["A.make"].route == "POST /api/v" and s["A.make"].calls == ["Foo"]
    assert s["A.t"].tags == ["test"] and f.tests[0]["name"] == "A.t"
    assert s["I"].kind == "interface" and s["I"].bases == ["J"] and s["E"].kind == "enum"
    assert "model" in s["Pet"].tags
    assert [(i.module, i.names) for i in f.imports] == [("java.util.List", []), ("com.x.z", [["*", ""]])]


def test_c_and_cpp():
    c = facts("src/c.c", '''#include <stdio.h>
#include "util.h"
#define MAX 10
typedef struct { int a; } Pt;
struct node { int v; };
enum color { RED };
static int counter = 0;
/* adds */
static int add(int a, int b) { return helper(a) + p->f(b); }
''')
    s = by(c)
    assert s["MAX"].kind == "macro" and s["Pt"].kind == "struct" and s["node"].kind == "struct" and s["color"].kind == "enum"
    assert s["add"].calls == ["helper", "p.f"] and not s["add"].exported and s["add"].doc == "adds"
    assert [(i.module, i.level) for i in c.imports] == [("stdio.h", 0), ("util.h", 1)]
    cpp = facts("src/f.cpp", '''namespace ns {
template <typename T> class Foo : public Bar, Baz {
public:
  int get() { return helper(); }
};
}
void ns::Foo::decl() { x.y(); obj->z(); }
TEST(Suite, Name) { }
''')
    s = by(cpp)
    assert s["ns.Foo"].bases == ["Bar", "Baz"] and s["ns.Foo.get"].kind == "method"
    assert s["ns.Foo.decl"].calls == ["x.y", "obj.z"]
    assert cpp.tests[0]["name"] == "Suite.Name" and cpp.is_test


def test_go():
    f = facts("pkg/user.go", '''package main
import (
  "fmt"
  str "strings"
)
const Max = 3
type User struct { gorm.Model; Name string `gorm:"size:10"` }
type Repo interface { Find(id int) User }
// Save persists.
func (u *User) Save(x int) error { return db.Do(x) }
func main() { r.GET("/users", list); http.HandleFunc("/h", handler) }
''')
    s = by(f)
    assert f.package == "main" and s["User"].kind == "struct" and "model" in s["User"].tags and s["User"].bases == ["gorm.Model"]
    assert s["Repo"].kind == "interface" and s["User.Save"].kind == "method" and s["User.Save"].doc == "Save persists."
    assert s["User.Save"].calls == ["db.Do"] and s["Max"].kind == "constant"
    assert [(a.method, a.path, a.handler) for a in f.apis] == [("GET", "/users", "list"), ("ANY", "/h", "handler")]
    assert [(i.module, i.alias) for i in f.imports] == [("fmt", ""), ("strings", "str")]
    t = facts("pkg/user_test.go", "package main\nfunc TestAdd(t *testing.T) { add(1) }\n")
    assert t.tests == [{"name": "TestAdd", "line": 2}] and t.is_test


def test_rust():
    f = facts("src/lib.rs", '''use std::collections::HashMap;
use crate::models::{User, Post as P};
mod util;
/// A user.
#[derive(Debug, Queryable)]
pub struct User { id: i32 }
pub trait Repo { fn find(&self) -> User; }
impl Repo for User { fn find(&self) -> User { helper(self.id) } }
impl User { pub fn new() -> Self { Self::build() } }
#[get("/x")]
async fn index() {}
#[test]
fn it_works() {}
fn main() { app.route("/y", get(handler)); }
''')
    s = by(f)
    assert s["User"].doc == "A user." and "model" in s["User"].tags and s["User"].bases == ["Repo"]   # `impl Repo for User`
    assert s["Repo"].kind == "trait" and s["User.find"].calls == ["helper"] and s["User.new"].calls == ["Self.build"]
    assert s["index"].route == "GET /x" and s["it_works"].tags == ["test"] and f.is_test
    assert {(a.method, a.path) for a in f.apis} == {("GET", "/x"), ("GET", "/y")}
    kinds = {(i.module, i.kind) for i in f.imports}
    assert ("crate::models", "") in kinds and ("util", "mod") in kinds


def test_missing_grammar_falls_back_to_regex(monkeypatch):
    monkeypatch.setattr(ex, "get_parser", lambda key: None)
    f = ex.extract_file("a.js", b"export function foo() { bar(); }\nclass K {}\n")
    assert f.parser == "regex" and {s.name for s in f.symbols} == {"foo", "K"}


def test_garbage_and_unsupported_files_never_raise():
    assert extract_file("x.py", b"\xff\xfe\x00garbage(((").parser in ("tree-sitter:python", "none", "error")
    assert extract_file("x.rs", b"fn ((( {{{").path == "x.rs"
    f = extract_file("notes.rb", b"def hello; end")
    assert f.parser == "none" and f.symbols == []
