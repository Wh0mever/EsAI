import { Field } from "../UI/Inputs/Inputs";
import { Button } from "../UI/Buttons/Buttons";
const className = "flex flex-col items-center justify-center w-auto gap-4 relative";
import { useTranslation } from "next-i18next";
import Cookies from "js-cookie";

export function SignInForm() {
	
	return (
		<form className={className}>
			<h3 className="font-bold text-2xl text-white py-2">Вход</h3>
			<Field type="email" name="email" placeholder="Email" />
			<Field type="password" name="password" placeholder="Пароль" />
			<Button onClick={() => {}} className="py-3 px-5 rounded-md bg-blue-700 w-100" type="submit">
				Войти
			</Button>
		</form>
	);
}

export function SignUpForm() {
	return (
		<form className={className}>
			<h3 className="font-bold text-2xl text-white py-2">Регистрация</h3>
			<Field type="email" name="email" placeholder="Email" />
			<Field type="password" name="password" placeholder="Пароль" />
			<Field type="password" name="password_repeat" placeholder="Повторите пароль" />
			<Button onClick={() => {}} className="py-3 px-5 rounded-md bg-blue-700 w-100" type="submit">
				Зарегистрироваться
			</Button>
		</form>
	);
}
