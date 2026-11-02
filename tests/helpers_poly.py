import textwrap
from pathlib import Path
def write_poly(root: Path):
    files = {
    "py/app/__init__.py": "",
    "py/app/main.py": '''
        from .services import eta
        from .services.eta import calculate, Base
        from . import util
        import app.util as u2
        class Child(Base):
            def run(self):
                self.helper()
                return super().run()
            def helper(self):
                return calculate(1)
        def handler():
            eta.calculate(2)
            util.fmt(3)
            u2.fmt(4)
            Child().run()
            local()
        def local(): pass
    ''',
    "py/app/services/__init__.py": "",
    "py/app/services/eta.py": '''
        class Base:
            def run(self): return 1
        def calculate(x):
            return x
    ''',
    "py/app/util.py": "def fmt(x):\n    return str(x)\n",
    "py/tests/test_main.py": "from app.main import handler\ndef test_it():\n    handler()\n",
    "web/src/api.ts": '''
        import { render as r } from "./ui";
        import * as ui from "./ui";
        import def from "./lib/index";
        import axios from "axios";
        export function load() { r(); ui.draw(); def(); }
        export class Svc { go() { return this.stop(); } stop() { return load(); } }
    ''',
    "web/src/ui.ts": "export function render() {}\nexport function draw() {}\n",
    "web/src/lib/index.ts": "export default function def() {}\n",
    "java/src/com/x/A.java": '''
        package com.x;
        import com.y.B;
        public class A extends B { public void a() { b(); new B().c(); B.stat(); } }
    ''',
    "java/src/com/y/B.java": '''
        package com.y;
        public class B { public void b() {} public void c() {} public static void stat() {} }
    ''',
    "go/go.mod": "module example.com/app\n\ngo 1.21\n\nrequire github.com/gin-gonic/gin v1.9.0\n",
    "go/main.go": '''
        package main
        import ("example.com/app/internal/db"; "github.com/gin-gonic/gin")
        func main() { db.Open(); helper() }
        func helper() {}
    ''',
    "go/internal/db/db.go": "package db\nfunc Open() {}\n",
    "rs/src/main.rs": "mod util;\nuse crate::models::User;\nfn main() { util::go(); User::new(); }\n",
    "rs/src/util.rs": "pub fn go() {}\n",
    "rs/src/models.rs": "pub struct User {}\nimpl User { pub fn new() -> User { User {} } }\n",
    "c/main.c": '#include "util.h"\n#include <stdio.h>\nint main() { return add(1,2); }\n',
    "c/util.h": "int add(int a, int b);\n",
    "c/util.c": '#include "util.h"\nint add(int a, int b) { return a + b; }\n',
    }
    for p, c in files.items():
        f = root / p; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(textwrap.dedent(c).lstrip("\n"))
