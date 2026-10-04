import { brl, centsToInput, parseMoney, signedBrl } from "./format";

const clean = (s: string) => s.replace(/\s/g, " ");

describe("parseMoney", () => {
  it.each([
    ["45", 4500],
    ["45,90", 4590],
    ["1.234,56", 123456],
    ["1.200", 120000],
    ["R$ 1.200,00", 120000],
    ["59.90", 5990],
    ["0,01", 1],
  ])("%s → %i centavos", (input, cents) => {
    expect(parseMoney(input)).toBe(cents);
  });

  it.each(["", "abc", "0", "-10", "1,234", "12,345"])("rejeita %s", (input) => {
    expect(parseMoney(input)).toBeNull();
  });
});

describe("formatação", () => {
  it("formata centavos em reais", () => {
    expect(clean(brl(123456))).toBe("R$ 1.234,56");
    expect(brl(null)).toBe("—");
  });
  it("sinaliza receita e despesa", () => {
    expect(clean(signedBrl(500, "income"))).toBe("+ R$ 5,00");
    expect(clean(signedBrl(500, "expense"))).toBe("− R$ 5,00");
  });
  it("converte para o campo de edição", () => {
    expect(centsToInput(4590)).toBe("45,90");
    expect(centsToInput(null)).toBe("");
  });
});
