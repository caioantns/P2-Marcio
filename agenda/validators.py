from django.core.exceptions import ValidationError


def validar_cpf(valor):
    """Valida os dígitos verificadores do CPF (espera apenas números)."""
    cpf = "".join(c for c in str(valor) if c.isdigit())
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        raise ValidationError("CPF inválido.")

    for tamanho in (9, 10):
        soma = sum(int(cpf[i]) * (tamanho + 1 - i) for i in range(tamanho))
        digito = (soma * 10) % 11 % 10
        if digito != int(cpf[tamanho]):
            raise ValidationError("CPF inválido.")
