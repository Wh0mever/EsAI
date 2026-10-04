"""Проверка адреса USDT TRC20 и TXID: опечатка в адресе — потерянная выплата."""
from ..errors import CreatorsError
from ..trc20 import TXID_RE, is_valid_address, normalize_txid
from . import factories as f

VALID = f.VALID_TRC20
BAD_CHECKSUM = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6u"


class AddressTests(f.CreatorsTestCase):
    def test_vectors(self):
        self.assertTrue(is_valid_address(f.VALID_TRC20))
        self.assertTrue(is_valid_address(f.VALID_TRC20_2))
        # Тот же адрес с другой последней буквой: контрольная сумма не сходится.
        self.assertFalse(is_valid_address(BAD_CHECKSUM))

    def test_every_single_character_typo_is_caught(self):
        alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        for position in range(1, len(VALID)):
            replacement = next(c for c in alphabet if c != VALID[position])
            typo = VALID[:position] + replacement + VALID[position + 1:]
            self.assertFalse(is_valid_address(typo), typo)

    def test_wrong_length(self):
        self.assertFalse(is_valid_address(VALID[:-1]))
        self.assertFalse(is_valid_address(VALID + "t"))
        self.assertFalse(is_valid_address(""))
        self.assertFalse(is_valid_address("T"))

    def test_wrong_prefix(self):
        # Адрес Bitcoin и адрес Ethereum — не Tron.
        self.assertFalse(is_valid_address("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"))
        self.assertFalse(is_valid_address("0x52908400098527886E0F7030069857D2E4169EE7"))
        self.assertFalse(is_valid_address("t" + VALID[1:]))
        self.assertFalse(is_valid_address("A" + VALID[1:]))

    def test_non_base58_characters(self):
        for bad in ("0", "O", "I", "l", "+", " ", "я"):
            self.assertFalse(is_valid_address(VALID[:10] + bad + VALID[11:]), bad)
        # Пробелы по краям сервис срезает сам, проверка их не прощает.
        self.assertFalse(is_valid_address(" " + VALID[:-1]))

    def test_not_a_string(self):
        for value in (None, 0, 12345, b"TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", ["T"], {}, 1.5):
            self.assertFalse(is_valid_address(value), repr(value))


class TxidTests(f.CreatorsTestCase):
    def test_normalised(self):
        self.assertEqual(normalize_txid("AB" * 32), "ab" * 32)
        self.assertEqual(normalize_txid("  " + "0f" * 32 + "\n"), "0f" * 32)
        self.assertEqual(normalize_txid("0x" + "AB" * 32), "ab" * 32)
        self.assertEqual(normalize_txid("0X" + "ab" * 32), "ab" * 32)
        self.assertTrue(TXID_RE.match(f.VALID_TXID))

    def test_invalid(self):
        for bad in (None, "", "a" * 63, "a" * 65, "g" * 64, "0x" + "a" * 63, "a" * 62 + "0x",
                    "я" * 64, " ".join(["a" * 32, "a" * 31])):
            with self.subTest(txid=bad), self.assertRaises(CreatorsError) as ctx:
                normalize_txid(bad)
            self.assertEqual(ctx.exception.code, "txid_invalid")
