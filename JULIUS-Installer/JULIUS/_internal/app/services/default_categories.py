"""Categorias criadas para cada novo usuário. Ele pode renomear, apagar e criar outras.

Combustível fica como subcategoria de Transporte (e não como categoria própria)
para que relatórios de transporte incluam o gasto com combustível.
"""

from sqlalchemy.orm import Session

from app.models import Category

# (nome, ícone lucide, cor, [subcategorias])
EXPENSE = [
    ("Alimentação", "utensils", "#E07A5F", ["Mercado", "Restaurantes", "Delivery", "Lanches"]),
    ("Moradia", "home", "#3D7A5C", ["Aluguel", "Condomínio", "Manutenção", "Móveis"]),
    (
        "Transporte",
        "car",
        "#4F6D7A",
        [
            "Combustível",
            "Uber/Táxi",
            "Transporte público",
            "Estacionamento",
            "Manutenção do veículo",
            "Pedágio",
        ],
    ),
    ("Saúde", "heart-pulse", "#C2185B", ["Farmácia", "Consultas", "Plano de saúde", "Exames"]),
    ("Educação", "graduation-cap", "#5C6BC0", ["Cursos", "Livros", "Mensalidade"]),
    ("Lazer", "party-popper", "#D4A017", ["Cinema", "Bares", "Shows e eventos", "Jogos"]),
    ("Roupas", "shirt", "#AD5C8C", ["Roupas", "Calçados", "Acessórios"]),
    ("Assinaturas", "repeat", "#7E57C2", ["Streaming", "Aplicativos", "Academia"]),
    ("Compras", "shopping-bag", "#8D6E63", ["Eletrônicos", "Casa", "Presentes"]),
    ("Contas", "receipt", "#00897B", ["Energia", "Água", "Internet", "Celular", "Gás"]),
    ("Impostos", "landmark", "#6D4C41", ["IPTU", "IPVA", "Imposto de renda", "Taxas"]),
    ("Viagens", "plane", "#0288D1", ["Hospedagem", "Passagens", "Passeios"]),
    ("Investimentos", "trending-up", "#2E7D32", []),
    ("Outros", "circle-dashed", "#78909C", []),
]

INCOME = [
    ("Salário", "briefcase", "#2E7D32", []),
    ("Renda extra", "sparkles", "#43A047", ["Freelance", "Vendas"]),
    ("Rendimentos", "piggy-bank", "#00897B", []),
    ("Reembolso", "undo-2", "#5C6BC0", []),
    ("Outras receitas", "circle-dashed", "#78909C", []),
]


def create_default_categories(db: Session, user_id: str) -> None:
    for kind, items in (("expense", EXPENSE), ("income", INCOME)):
        for name, icon, color, subs in items:
            parent = Category(user_id=user_id, name=name, kind=kind, icon=icon, color=color)
            db.add(parent)
            db.flush()
            for sub in subs:
                db.add(Category(user_id=user_id, parent_id=parent.id, name=sub, kind=kind))
