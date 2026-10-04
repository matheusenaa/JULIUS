import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router";

import { Button, Field, Logo } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { queryClient } from "../lib/queries";
import type { User } from "../lib/types";

function AuthLayout({ children, tagline }: { children: React.ReactNode; tagline: string }) {
  return (
    <main className="auth">
      <div className="auth-card">
        <Logo to="/entrar" />
        <p className="tagline">{tagline}</p>
        {children}
      </div>
    </main>
  );
}

export function Login() {
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const user = await api<User>("/api/auth/login", { body: { email: email.trim(), password } });
      queryClient.setQueryData(["me"], user);
      navigate(from, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout tagline="Seu dinheiro, organizado em segundos.">
      <form className="form" onSubmit={submit}>
        <Field label="E-mail">
          <input className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Senha">
          <input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {error && (
          <div className="alert danger" role="alert">
            {error}
          </div>
        )}
        <Button type="submit" variant="primary" block loading={loading}>
          Entrar
        </Button>
      </form>
      <p className="small muted">
        Ainda não tem conta? <Link to="/criar-conta">Criar conta</Link>
      </p>
    </AuthLayout>
  );
}

export function Register() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password.length < 10) return setError("A senha precisa ter pelo menos 10 caracteres.");
    setLoading(true);
    setError(null);
    try {
      const user = await api<User>("/api/auth/register", { body: { name: name.trim(), email: email.trim(), password } });
      queryClient.setQueryData(["me"], user);
      navigate("/boas-vindas", { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout tagline="Comece a entender para onde vai seu dinheiro.">
      <form className="form" onSubmit={submit}>
        <Field label="Seu nome">
          <input className="input" autoComplete="name" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="E-mail">
          <input className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Senha" hint="Mínimo de 10 caracteres. Uma frase fácil de lembrar funciona bem.">
          <input className="input" type="password" autoComplete="new-password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {error && (
          <div className="alert danger" role="alert">
            {error}
          </div>
        )}
        <Button type="submit" variant="primary" block loading={loading}>
          Criar conta
        </Button>
      </form>
      <p className="small muted">
        Já tem conta? <Link to="/entrar">Entrar</Link>
      </p>
    </AuthLayout>
  );
}
