from models import Usuario, Curriculo
from fastapi import FastAPI, Request, Form, Depends, APIRouter, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session

from database import SessionLocal, engine
import models
from models import Curriculo
from auth import hash_senha, verificar_senha, validar_forca_senha, gerar_senha_temporaria
from ia import processar_curriculo

import json
import os
import shutil
import requests

# =========================
# BASE DIR
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# =========================
# APP
# =========================
app = FastAPI()
templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.mount("/static", StaticFiles(directory="static"), name="static")

from database import engine
import models

models.Base.metadata.create_all(bind=engine)

print("BANCO NOVO CRIADO")

# =========================
# INICIALIZAÇÃO DO BANCO
# =========================
models.Base.metadata.create_all(bind=engine)

import os

if os.getenv("RESET_DB") == "true":
    import models
    from database import engine
    models.Base.metadata.drop_all(bind=engine)
    models.Base.metadata.create_all(bind=engine)
# =========================
# ROUTER
# =========================
router = APIRouter()

# =========================
# DB
# =========================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =========================
# ROTAS PÚBLICAS
# =========================

@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
    request=request,
    name="index.html",
    context={}
)

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={}
    )

@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={}
    )

@router.post("/register")
def register(
    request: Request,
    email: str = Form(...),
    senha: str = Form(...),
    db: Session = Depends(get_db)
):
    usuario = db.query(models.Usuario).filter(
        models.Usuario.email == email
    ).first()

    if usuario:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "erro": "Usuário já existe"
            }
        )

    valida, msg = validar_forca_senha(senha)

    if not valida:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "erro": msg
            }
        )

    novo_usuario = models.Usuario(
        email=email,
        senha=hash_senha(senha)
    )

    db.add(novo_usuario)
    db.commit()

    return RedirectResponse(
        url="/login",
        status_code=302
    )

@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    senha: str = Form(...),
    db: Session = Depends(get_db)
):
    usuario = db.query(models.Usuario).filter(models.Usuario.email == email).first()

    if not usuario or not verificar_senha(senha, usuario.senha):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "erro": "Login inválido"
            }
        )

    response = RedirectResponse(url="/dashboard", status_code=302)

    response.set_cookie(
        key="user_id",
        value=str(usuario.id),
        httponly=True
    )

    return response

@router.get("/recuperar", response_class=HTMLResponse)
def recuperar_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="recuperar.html",
        context={}
    )

@router.post("/recuperar")
def recuperar_senha(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    usuario = db.query(models.Usuario).filter(models.Usuario.email == email).first()

    if not usuario:
        return templates.TemplateResponse("recuperar.html", {
            "request": request,
            "erro": "Email não encontrado"
        })

    nova_senha = gerar_senha_temporaria()
    usuario.senha = hash_senha(nova_senha)
    db.commit()

    return templates.TemplateResponse("recuperar.html", {
        "request": request,
        "sucesso": f"Sua nova senha é: {nova_senha}"
    })

@router.get("/logout")
def logout():
    response = RedirectResponse(url="/")
    response.delete_cookie("user_id")
    return response

# =========================
# ROTAS PROTEGIDAS
# =========================

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return RedirectResponse(url="/")

    usuario = db.query(Usuario).filter(Usuario.id == int(user_id)).first()

    if not usuario:
        return RedirectResponse(url="/")

    curriculo = db.query(Curriculo).filter(Curriculo.user_id == usuario.id).first()

    return templates.TemplateResponse(
    request=request,
    name="dashboard.html",
    context={
        "usuario": usuario,
        "curriculo": curriculo,
        "pago": request.cookies.get("pago") == "true"
    }
)

@router.get("/criar-curriculo", response_class=HTMLResponse)
def pagina_criar(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return RedirectResponse(url="/")

    existente = db.query(Curriculo).filter(Curriculo.user_id == int(user_id)).first()

    if existente:
        return RedirectResponse(url="/dashboard")

    return templates.TemplateResponse(
        request=request,
        name="criar_curriculo.html",
        context={}
    )


@router.post("/criar-curriculo")
def criar_curriculo(
    request: Request,
    texto: str = Form(...),
    foto: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return RedirectResponse(url="/")

    dados_tratados = processar_curriculo(texto)

    if not dados_tratados:
        return templates.TemplateResponse(
            request=request,
            name="criar_curriculo.html",
            context={
                "erro": "Erro ao processar currículo. Tente novamente."
            }
        )

    caminho_foto = None

    if foto and foto.filename:
        os.makedirs("static/fotos", exist_ok=True)
        temp_path = os.path.join("static", "fotos", f"temp_{user_id}_{foto.filename}")

        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(foto.file, buffer)

        caminho_foto = temp_path

    novo = Curriculo(
        user_id=int(user_id),
        dados_brutos=texto,
        dados_tratados=json.dumps(dados_tratados),
        foto=caminho_foto
    )

    db.add(novo)
    db.commit()

    return RedirectResponse(url="/dashboard", status_code=302)

@router.get("/editar-curriculo", response_class=HTMLResponse)
def editar_curriculo(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return RedirectResponse(url="/")

    curriculo = db.query(Curriculo).filter(
        Curriculo.user_id == int(user_id)
    ).first()

    if not curriculo:
        return RedirectResponse(url="/criar-curriculo")

    return templates.TemplateResponse(
        request=request,
        name="editar_curriculo.html",
        context={
            "curriculo": curriculo
        }
    )

@router.post("/editar-curriculo")
def salvar_edicao(
    request: Request,
    dados_brutos: str = Form(...),
    foto: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return RedirectResponse(url="/")

    curriculo = db.query(Curriculo).filter(
        Curriculo.user_id == int(user_id)
    ).first()

    if not curriculo:
        return RedirectResponse(url="/dashboard")

    dados_novos = processar_curriculo(dados_brutos)

    if not dados_novos:
        return templates.TemplateResponse(
            request=request,
            name="editar_curriculo.html",
            context={
                "curriculo": curriculo,
                "erro": "Erro ao processar currículo. Tente novamente."
            }
        )

    try:
        dados_antigos = json.loads(curriculo.dados_tratados) if curriculo.dados_tratados else {}

        if dados_antigos:
            if "nome" in dados_antigos and dados_antigos["nome"]:
                dados_novos["nome"] = dados_antigos["nome"]

            if "resumo" in dados_antigos and dados_antigos["resumo"]:
                dados_novos["resumo"] = dados_antigos["resumo"]

    except Exception as e:
        print("Erro ao manter dados antigos:", e)

    if foto and foto.filename:
        os.makedirs("static/fotos", exist_ok=True)

        caminho_foto = os.path.join(
            "static",
            "fotos",
            f"user_{user_id}_{foto.filename}"
        )

        with open(caminho_foto, "wb") as buffer:
            shutil.copyfileobj(foto.file, buffer)

        curriculo.foto = caminho_foto

    curriculo.dados_brutos = dados_brutos
    curriculo.dados_tratados = json.dumps(dados_novos) if dados_novos else None

    db.commit()

    return RedirectResponse(
        url="/dashboard",
        status_code=302
    )

# =========================
# PREVIEW E MODELOS
# =========================

@router.get("/preview")
def preview(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return RedirectResponse(url="/")

    curriculo = db.query(Curriculo).filter(
        Curriculo.user_id == int(user_id)
    ).first()

    if not curriculo:
        return RedirectResponse(url="/dashboard")

    try:
        dados = json.loads(curriculo.dados_tratados) if curriculo.dados_tratados else {}
    except:
        return RedirectResponse(url="/dashboard")

    modelo = curriculo.modelo or 1

    if modelo == 2:
        template = "preview_modelo2.html"
    elif modelo == 3:
        template = "preview_modelo3.html"
    elif modelo == 4:
        template = "preview_modelo4.html"
    else:
        template = "preview.html"

    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "dados": dados,
            "curriculo": curriculo
        }
    )

@router.get("/preview_modelo2")
def preview_modelo2(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return RedirectResponse(url="/")

    curriculo = db.query(Curriculo).filter(Curriculo.user_id == int(user_id)).first()

    if not curriculo:
        return RedirectResponse(url="/dashboard")

    dados = json.loads(curriculo.dados_tratados) if curriculo.dados_tratados else {}

    return templates.TemplateResponse(
        request=request,
        name="preview_modelo2.html",
        context={
            ...
        }
    )

@router.get("/preview_modelo3")
def preview_modelo3(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return RedirectResponse(url="/")

    curriculo = db.query(Curriculo).filter(Curriculo.user_id == int(user_id)).first()

    if not curriculo:
        return RedirectResponse(url="/dashboard")

    dados = json.loads(curriculo.dados_tratados) if curriculo.dados_tratados else {}

    return templates.TemplateResponse(
        request=request,
        name="preview_modelo3.html",
        context={
            ...
        }
    )

@router.get("/preview_modelo4")
def preview_modelo4(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return RedirectResponse(url="/")

    curriculo = db.query(Curriculo).filter(Curriculo.user_id == int(user_id)).first()

    if not curriculo:
        return RedirectResponse(url="/dashboard")

    dados = json.loads(curriculo.dados_tratados) if curriculo.dados_tratados else {}

    return templates.TemplateResponse(
        request=request,
        name="preview_modelo4.html",
        context={
            ...
        }
    )

@router.get("/salvar_modelo/{modelo}")
def salvar_modelo(modelo: int, request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return RedirectResponse(url="/")

    curriculo = db.query(Curriculo).filter(Curriculo.user_id == int(user_id)).first()

    if not curriculo:
        return RedirectResponse(url="/dashboard")

    curriculo.modelo = modelo
    db.commit()

    return RedirectResponse(url="/dashboard")

# =========================
# PLANOS E PAGAMENTO
# =========================

@router.get("/planos", response_class=HTMLResponse)
def planos(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="planos.html",
        context={}
    )

@router.get("/assinar")
def assinar():
    return RedirectResponse(url="/criar-pagamento")

@router.get("/pagamento", response_class=HTMLResponse)
def pagamento(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pagamento.html",
        context={}
    )

from datetime import datetime

@router.get("/preview-check")
def preview_check(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return RedirectResponse(url="/")

    usuario = db.query(Usuario).filter(Usuario.id == int(user_id)).first()

    if not usuario:
        return RedirectResponse(url="/")

    # ✅ SE PAGOU → LIBERA
    if usuario.pago_ate and datetime.now() < usuario.pago_ate:
        return RedirectResponse(url="/preview")

    # ❌ NÃO PAGOU → VAI DIRETO PRO PAGAMENTO (PIX)
    return RedirectResponse(url="/criar-pagamento")

@router.get("/liberar")
def liberar():
    response = RedirectResponse(url="/preview")
    response.set_cookie(
        key="pago",
        value="true",
        max_age=2592000
)
    return response

@app.get("/reset-pagamento")
def reset_pagamento():
    return {"status": "ok"}

# =========================
# INCLUI ROUTER NO APP
# =========================
@router.get("/criar-pagamento")
def criar_pagamento():
    token = os.getenv("MERCADO_PAGO_TOKEN")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    body = {
        "items": [
            {
                "title": "Prime Currículo - Acesso 30 dias",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": 14.90
            }
        ]
    }

    response = requests.post(
        "https://api.mercadopago.com/checkout/preferences",
        json=body,
        headers=headers
    )

    data = response.json()

    return RedirectResponse(url=data["init_point"])

app.include_router(router)