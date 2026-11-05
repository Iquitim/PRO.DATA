"""Para onde uma API pode ser chamada (spec 026).

O destino é classificado pelo endereço real, não pelo nome. Endereço público é livre; rede interna só com a
lista autorizada, num arquivo que exige administrador para alterar; metadados de nuvem, nunca. Sem servidor
central, isto evita engano e distração, não um usuário decidido a burlar.
"""

from __future__ import annotations

import fnmatch
import ipaddress
import json
import logging
import os
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

POLICY_ENV = "PRODATA_POLICY_FILE"
POLICY_KEY = "servidores_internos"
# Respondem com credenciais da máquina em nuvem: nenhuma lista libera.
METADATA_IPS = {"169.254.169.254", "169.254.170.2", "100.100.100.200", "fd00:ec2::254"}
METADATA_NAMES = {"metadata.google.internal", "metadata", "instance-data", "instance-data.ec2.internal"}

Address = ipaddress.IPv4Address | ipaddress.IPv6Address


def policy_path() -> Path:
    # A variável só vale fora do executável: no programa instalado, o caminho é o protegido.
    if not getattr(sys, "frozen", False) and os.environ.get(POLICY_ENV):
        return Path(os.environ[POLICY_ENV])
    return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "PRO.DATA" / "politica.json"


@dataclass
class Policy:
    allowed: list[str] = field(default_factory=list)

    def allows(self, host: str, addresses: list[Address]) -> bool:
        name = host.lower()
        for entry in self.allowed:
            rule = entry.strip().lower()
            if not rule:
                continue
            if fnmatch.fnmatch(name, rule):
                return True
            try:
                network = ipaddress.ip_network(rule, strict=False)
            except ValueError:
                continue
            if any(a in network for a in addresses if a.version == network.version):
                return True
        return False


def load_policy() -> Policy:
    """Sem arquivo, nada interno é liberado. Arquivo ilegível vale como lista vazia: na dúvida, recusa."""
    path = policy_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        hosts = data.get(POLICY_KEY, [])
        return Policy([str(h) for h in hosts] if isinstance(hosts, list) else [])
    except FileNotFoundError:
        return Policy()
    except (OSError, ValueError, AttributeError) as exc:
        log.warning("Política de APIs ilegível em %s: %s", path, exc)
        return Policy()


def resolve(host: str) -> list[str]:
    """Endereços do nome. Se não resolver, a própria conexão explica o erro. Testes trocam esta função."""
    try:
        return sorted({str(info[4][0]) for info in socket.getaddrinfo(host, None)})
    except OSError, UnicodeError:
        return []


def addresses_of(host: str) -> list[Address]:
    try:
        return [_plain(ipaddress.ip_address(host))]
    except ValueError:
        pass
    found = []
    for raw in resolve(host):
        try:
            found.append(_plain(ipaddress.ip_address(raw.split("%", 1)[0])))
        except ValueError:
            continue
    return found


def _plain(address: Address) -> Address:
    """::ffff:10.0.0.1 é o mesmo 10.0.0.1."""
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped or address


def _is_internal(address: Address) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


@dataclass(frozen=True)
class Destination:
    host: str
    metadata: bool
    internal: bool
    loopback: bool
    listed: bool


def classify(url: str, policy: Policy) -> Destination:
    host = (urlsplit(url).hostname or "").lower()
    addresses = addresses_of(host)
    metadata = host in METADATA_NAMES or any(str(a) in METADATA_IPS for a in addresses)
    loopback = host == "localhost" or (bool(addresses) and all(a.is_loopback for a in addresses))
    internal = host == "localhost" or any(_is_internal(a) for a in addresses)
    return Destination(host, metadata, internal, loopback, policy.allows(host, addresses))
