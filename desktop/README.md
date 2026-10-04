# JULIUS para computador

## Por que este formato

| Opção | Tamanho | Avaliação |
|---|---|---|
| Electron | ~150 MB, alto consumo de RAM | Descartado: pesado demais para o objetivo (e para máquinas de 8 GB) |
| Tauri | ~10 MB + servidor Python | Ótimo resultado final, mas exige toolchain Rust e empacotar o Python como "sidecar". Evolução natural |
| **PWA instalada** | 0 MB extra | Já funciona: no Edge/Chrome, abra o JULIUS e use "Instalar aplicativo". Depende do servidor online |
| **Executável local (este)** | ~40 MB | Servidor + banco no próprio PC, funciona sem internet e sincroniza com o servidor online. Windows, Linux e macOS (gerar em cada sistema) |

## Usar sem gerar executável

```powershell
& "$env:USERPROFILE\.venvs\julius\Scripts\python.exe" desktop\launcher.py
```

Dados ficam em `%LOCALAPPDATA%\JULIUS` (banco `julius.db`, pasta `arquivos`, `julius.log`).
Chaves de IA opcionais: crie `%LOCALAPPDATA%\JULIUS\julius.env` com, por exemplo, `AI_PROVIDER=gemini` e `GEMINI_API_KEY=...`.

## Gerar o executável (Windows)

```powershell
cd frontend; npx vite build; cd ..
& "$env:USERPROFILE\.venvs\julius\Scripts\pip.exe" install pyinstaller
& "$env:USERPROFILE\.venvs\julius\Scripts\pyinstaller.exe" desktop\julius.spec --noconfirm
# resultado: dist\JULIUS\JULIUS.exe
```

Em Linux/macOS o mesmo comando gera o executável do sistema (PyInstaller não faz compilação cruzada).

## Sincronizar com o servidor online

No app instalado: Ajustes → Sincronização → informe o endereço do servidor online, e-mail e senha.
A partir daí, alterações feitas no computador (mesmo sem internet) vão para o servidor e as feitas
no celular chegam ao computador. Se o mesmo lançamento mudar nos dois lados, o JULIUS pergunta qual
versão manter.
