"""Стартовое наполнение библиотеки студии: разделы, герои, сцены.

Клиент попросил упор на трендовое и визуально интересное — то, ради чего
человеку захочется поэкспериментировать, а значит и докупить кредиты. Отсюда
подбор: капибара и ленивец (мем-звери, которые сейчас везде), панда-ниндзя и
кот-детектив (узнаваемые архетипы), скейтер и футболист (спорт, близко
подросткам), пингвин-диджей и единорог (яркая картинка).

Разделы придуманы не «по жанру вообще», а по тому, из чего реально
складывается короткий мультфильм: появление героя, путь, чудо, столкновение,
финал. Внутри каждого — 3-5 сцен, как и просил клиент.

Стиль у всех сцен ОДИН. Это то, что превращает набор роликов в один
мультфильм, а не в нарезку: одинаковая подача света, цвета и камеры.

Данные лежат отдельно от команды, потому что ими же пользуется и админка при
модерации пользовательских работ (раздел выбирается из этого же списка).
"""

STYLE = ("3D cartoon animation style, Pixar-like rendering, soft cinematic lighting, "
         "vibrant saturated colors, shallow depth of field, family-friendly")

# (код, название, значок, порядок)
CATEGORIES = [
    ("start", "Начало истории", "🎬", 10),
    ("adventure", "Приключения", "🧭", 20),
    ("magic", "Волшебство", "✨", 30),
    ("space", "Космос", "🚀", 40),
    ("action", "Экшен", "⚡", 50),
    ("funny", "Смешное", "😄", 60),
    ("sport", "Спорт", "⚽", 70),
    ("finale", "Финал", "🌅", 80),
]

# (имя, описание для моделей, как рисовать, раздел)
CHARACTERS = [
    ("Кот-супергерой", "a ginger cat superhero in a blue cape with small goggles",
     "a friendly ginger cat superhero wearing a blue cape and small flight goggles", "action"),
    ("Девочка-космонавт", "a little girl astronaut with red braids in a white spacesuit",
     "a cheerful little girl astronaut with red braids, white spacesuit with orange stripes", "space"),
    ("Дракончик", "a small round green dragon with tiny wings",
     "a small round friendly green dragon with tiny wings and big eyes", "magic"),
    ("Робот-помощник", "a small white round robot with glowing blue eyes",
     "a small white rounded helper robot with glowing blue eyes and short arms", "space"),
    # --- трендовое, ради чего захочется попробовать ---
    ("Капибара", "a calm capybara in tiny orange sunglasses",
     "a very calm chubby capybara wearing tiny round orange sunglasses, relaxed smile", "funny"),
    ("Ленивец", "a sleepy sloth in a knitted scarf",
     "a sleepy smiling sloth wearing a cozy knitted scarf, droopy eyes", "funny"),
    ("Панда-ниндзя", "a panda ninja in a black headband",
     "a chubby panda ninja wearing a black headband and belt, confident pose", "action"),
    ("Кот-детектив", "a grey cat detective in a beige trench coat and hat",
     "a grey cat detective wearing a beige trench coat and a small fedora hat", "adventure"),
    ("Лисёнок-путешественник", "a little fox explorer with a backpack",
     "a little orange fox explorer with a small green backpack and a compass", "adventure"),
    ("Единорог", "a pastel unicorn with a rainbow mane",
     "a cute pastel white unicorn with a soft rainbow mane and golden horn", "magic"),
    ("Пингвин-диджей", "a penguin dj with big headphones",
     "a cool penguin dj wearing oversized golden headphones and sunglasses", "funny"),
    ("Мальчик-скейтер", "a boy skater in a cap and hoodie with a skateboard",
     "a cheerful boy skater in a backwards cap and yellow hoodie holding a skateboard", "sport"),
    ("Тигрёнок-футболист", "a tiger cub footballer in a red jersey",
     "an energetic tiger cub in a red football jersey with a ball under his paw", "sport"),
    ("Совёнок-волшебник", "a baby owl wizard in a starry purple hat",
     "a small round baby owl wizard wearing a starry purple pointed hat", "magic"),
    ("Акулёнок", "a friendly baby shark with big eyes",
     "a friendly chubby baby shark with big round eyes and a small smile", "funny"),
    ("Девочка-рыцарь", "a little girl knight in shiny silver armor",
     "a brave little girl knight in shiny silver armor with a small sword", "adventure"),
]

# (код, название, подпись, что в кадре, что движется, секунд, раздел)
PRESETS = [
    # --- Начало истории ---
    ("hero-appears", "Герой появляется", "Выход на крышу на рассвете",
     "the character stands heroically on a rooftop at sunrise, city skyline behind, wind in the air",
     "slow cinematic push-in on the character, cape and hair flutter, sun flares softly", 5, "start"),
    ("wakes-up", "Пробуждение", "Утро, герой просыпается",
     "the character waking up in a cozy sunlit bedroom, stretching, morning light through the window",
     "the character stretches and yawns, dust motes float in the sunbeam, camera slowly rises", 5, "start"),
    ("door-opens", "Дверь в новый мир", "Открывает светящуюся дверь",
     "the character opening a tall glowing door, bright light pouring out, silhouette against the glow",
     "the door opens wider, light floods the frame, the character steps forward", 5, "start"),
    ("city-walk", "Выход в город", "Идёт по утренней улице",
     "the character walking along a bright morning city street, shop windows and trees around",
     "tracking shot alongside the walking character, background slides past smoothly", 5, "start"),

    # --- Приключения ---
    ("jungle", "Джунгли", "Пробирается сквозь заросли",
     "the character exploring a dense sunlit jungle, huge leaves and hanging vines, parrots in the background",
     "the character pushes leaves aside and steps forward, light rays shift through the canopy", 5, "adventure"),
    ("pirate-ship", "Пиратский корабль", "На палубе в открытом море",
     "the character standing on the deck of a wooden pirate ship at sea, sails and ropes above",
     "the ship rocks on the waves, sails billow, camera circles the character", 5, "adventure"),
    ("desert", "Пустыня", "Идёт по барханам на закате",
     "the character walking across golden sand dunes at sunset, long shadow behind",
     "wind lifts sand, the character walks forward, camera pulls back to reveal the vast desert", 5, "adventure"),
    ("underwater", "Под водой", "Плывёт среди рыб и кораллов",
     "the character swimming underwater among colorful coral reefs and tropical fish, sunbeams from above",
     "the character glides forward, bubbles rise, fish scatter around", 5, "adventure"),
    ("mountain-top", "На вершине", "Взбирается на пик",
     "the character reaching a snowy mountain peak, clouds below, flag planted nearby",
     "the character raises arms in triumph, wind blows snow, camera rises above the peak", 5, "adventure"),

    # --- Волшебство ---
    ("magic-world", "Волшебный мир", "Попадает в светящийся лес",
     "the character walking into a glowing magical forest, floating lights, giant mushrooms",
     "the character walks forward, glowing particles drift around, camera follows gently", 5, "magic"),
    ("spell-cast", "Заклинание", "Творит волшебство руками",
     "the character casting a glowing spell with both hands, swirling magic light around the palms",
     "magic light swirls and bursts outward, the character leans back from the glow", 5, "magic"),
    ("floating-island", "Летающий остров", "Стоит на парящей скале",
     "the character standing on a floating island in the sky, waterfalls pouring off the edges, clouds around",
     "clouds drift past, waterfalls fall endlessly, camera orbits the island slowly", 5, "magic"),
    ("potion", "Волшебное зелье", "Варит светящееся зелье",
     "the character stirring a bubbling glowing potion in a big cauldron, sparkles rising",
     "the potion bubbles and glows brighter, sparkles float up, the character leans closer", 5, "magic"),

    # --- Космос ---
    ("space", "Космос", "Парит среди звёзд",
     "the character floating in outer space near a colorful nebula, planets in the distance",
     "slow weightless rotation of the character, stars drift by, nebula glows and shifts", 5, "space"),
    ("moon-walk", "На Луне", "Прыгает по лунной поверхности",
     "the character bouncing across the grey lunar surface, Earth rising in the black sky behind",
     "the character makes a slow low-gravity leap, dust puffs up, camera follows the arc", 5, "space"),
    ("spaceship", "В рубке корабля", "За штурвалом звездолёта",
     "the character sitting at the controls of a bright spaceship cockpit, stars streaking past the window",
     "stars streak faster past the window, panel lights blink, the character grips the controls", 5, "space"),
    ("alien-meet", "Встреча с пришельцем", "Знакомится с добрым инопланетянином",
     "the character meeting a small friendly glowing alien on a purple planet under two moons",
     "the alien floats closer and waves, both react warmly, camera circles them", 5, "space"),

    # --- Экшен ---
    ("takes-off", "Взлёт", "Отрывается от земли и уходит вверх",
     "the character crouches and then leaps upward from a city street, dust swirling below",
     "the character launches upward, camera tilts up following the flight, motion blur streaks", 5, "action"),
    ("flying", "Полёт над городом", "Летит сквозь облака",
     "the character flying high above the clouds, city far below, warm sunlight",
     "smooth flight forward, clouds rush past the camera, cape streams behind", 5, "action"),
    ("chase", "Погоня", "Мчится по улицам",
     "the character running fast through a colorful city street, motion energy, onlookers blurred",
     "fast tracking shot alongside the running character, speed lines, camera shake", 5, "action"),
    ("battle", "Схватка", "Противостоит большому роботу",
     "the character facing a huge friendly-looking robot in a city square, determined pose",
     "the character raises fists, the robot leans in, camera pushes past them dramatically", 5, "action"),
    ("dino-meets", "Встреча с динозавром", "Знакомится с добрым динозавром",
     "the character meeting a friendly giant dinosaur in a sunny prehistoric valley",
     "the dinosaur lowers its head toward the character, both react warmly, camera circles slowly", 5, "action"),

    # --- Смешное ---
    ("funny-fall", "Смешное падение", "Забавно спотыкается и встаёт",
     "the character comically slips on a banana peel in a bright city park, exaggerated cartoon pose",
     "the character slips, tumbles and springs back up with a grin, bouncy cartoon timing", 4, "funny"),
    ("dance", "Танец", "Отжигает под музыку",
     "the character dancing energetically on a colorful stage with disco lights",
     "the character dances with bouncy exaggerated moves, lights flash in rhythm", 5, "funny"),
    ("cake-face", "Торт в лицо", "Ловит торт лицом",
     "the character standing in a bright kitchen as a cream cake flies toward the camera",
     "the cake hits, cream splatters, the character blinks and slowly smiles", 4, "funny"),
    ("sleepy", "Засыпает на ходу", "Клюёт носом и падает в подушки",
     "the character yawning hugely on a giant pile of soft pillows in a cozy room",
     "the character yawns, sways and flops backward into the pillows, feathers puff up", 4, "funny"),

    # --- Спорт ---
    ("football", "Гол!", "Забивает решающий гол",
     "the character kicking a football toward the goal on a bright stadium field, crowd behind",
     "the character strikes the ball, it flies toward the goal, camera follows the shot", 5, "sport"),
    ("skate", "Трюк на скейте", "Взлетает на рампе",
     "the character riding a skateboard up a ramp in a sunny skatepark, mid-air trick",
     "the character launches off the ramp, spins the board, lands and rolls away", 5, "sport"),
    ("finish-line", "Финиш", "Пересекает финишную ленту",
     "the character sprinting through a finish line ribbon on a running track, crowd cheering",
     "the ribbon breaks across the chest, arms rise in victory, confetti falls", 5, "sport"),

    # --- Финал ---
    ("goes-home", "Возвращение домой", "Уходит на закате",
     "the character walking home along a quiet street at sunset, long shadows, warm light",
     "the character walks away from camera, sun sets behind, gentle slow pull-back", 5, "finale"),
    ("group-hug", "Все вместе", "Обнимается с друзьями",
     "the character hugging friendly cartoon friends in a warm sunset meadow",
     "the group pulls into a hug, everyone laughs, camera slowly rises above them", 5, "finale"),
    ("stars-wish", "Загадывает желание", "Смотрит на падающую звезду",
     "the character sitting on a hill at night looking up at a starry sky, a shooting star crossing it",
     "a shooting star streaks across, the character closes eyes and smiles, fireflies drift", 5, "finale"),
    ("the-end", "Титры", "Машет на прощание",
     "the character waving goodbye in front of a soft glowing sunset background, warm colors",
     "the character waves, light warms and blooms, camera slowly pulls back", 4, "finale"),
]


# --- Переводы библиотеки ---------------------------------------------------
# Клиент требует, чтобы на выбранном языке не оставалось чужих слов. Интерфейс
# студии живёт в locales, а названия сцен и героев — это содержимое базы, и
# переводятся они так же, как статьи блога: отдельным полем на язык.
# Ключ — slug сцены или раздела, у героев — русское имя (оно уникально).

CATEGORY_TRANSLATIONS = {
    "start": ("Story start", "Окуянын башталышы"),
    "adventure": ("Adventure", "Укмуштуу окуялар"),
    "magic": ("Magic", "Сыйкыр"),
    "space": ("Space", "Космос"),
    "action": ("Action", "Экшен"),
    "funny": ("Funny", "Күлкүлүү"),
    "sport": ("Sport", "Спорт"),
    "finale": ("Finale", "Финал"),
}

CHARACTER_TRANSLATIONS = {
    "Кот-супергерой": ("Superhero cat", "Мышык-супербаатыр"),
    "Девочка-космонавт": ("Girl astronaut", "Кыз-космонавт"),
    "Дракончик": ("Little dragon", "Кичинекей ажыдаар"),
    "Робот-помощник": ("Helper robot", "Жардамчы робот"),
    "Капибара": ("Capybara", "Капибара"),
    "Ленивец": ("Sloth", "Ленивец"),
    "Панда-ниндзя": ("Ninja panda", "Панда-ниндзя"),
    "Кот-детектив": ("Detective cat", "Мышык-детектив"),
    "Лисёнок-путешественник": ("Traveller fox cub", "Саякатчы түлкүчө"),
    "Единорог": ("Unicorn", "Единорог"),
    "Пингвин-диджей": ("DJ penguin", "Пингвин-диджей"),
    "Мальчик-скейтер": ("Skater boy", "Скейтчи бала"),
    "Тигрёнок-футболист": ("Footballer tiger cub", "Футболчу жолборсчо"),
    "Совёнок-волшебник": ("Wizard owlet", "Сыйкырчы үкүчө"),
    "Акулёнок": ("Baby shark", "Кичинекей акула"),
    "Девочка-рыцарь": ("Knight girl", "Рыцарь кыз"),
}

# slug: (title_en, subtitle_en, title_kg, subtitle_kg)
PRESET_TRANSLATIONS = {
    "hero-appears": ("The hero appears", "Stepping onto the roof at dawn",
                     "Каарман пайда болот", "Таң атканда чатырга чыгуу"),
    "wakes-up": ("Waking up", "Morning, the hero wakes",
                 "Ойгонуу", "Эртең менен каарман ойгонот"),
    "door-opens": ("Door to a new world", "Opens a glowing door",
                   "Жаңы дүйнөгө эшик", "Жаркыраган эшикти ачат"),
    "city-walk": ("Out into the city", "Walking the morning street",
                  "Шаарга чыгуу", "Эртең мененки көчө менен басат"),
    "jungle": ("Jungle", "Pushing through the thicket",
               "Джунгли", "Чытырман токойдон өтөт"),
    "pirate-ship": ("Pirate ship", "On deck in the open sea",
                    "Каракчы кемеси", "Ачык деңизде палубада"),
    "desert": ("Desert", "Walking the dunes at sunset",
               "Чөл", "Күн батканда кум дөбөлөрүндө"),
    "underwater": ("Underwater", "Swimming among fish and coral",
                   "Суу астында", "Балыктар менен маржандардын арасында сүзөт"),
    "mountain-top": ("On the summit", "Climbing to the peak",
                     "Чокуда", "Чокуга чыгат"),
    "magic-world": ("Magic world", "Enters a glowing forest",
                    "Сыйкырдуу дүйнө", "Жаркыраган токойго кирет"),
    "spell-cast": ("Spellcasting", "Works magic with their hands",
                   "Сыйкыр", "Колу менен сыйкыр жасайт"),
    "floating-island": ("Floating island", "Standing on a hovering rock",
                        "Учуучу арал", "Асмандагы аскада турат"),
    "potion": ("Magic potion", "Brewing a glowing potion",
               "Сыйкырдуу дары", "Жаркыраган дары кайнатат"),
    "space": ("Space", "Floating among the stars",
              "Космос", "Жылдыздардын арасында калкып жүрөт"),
    "moon-walk": ("On the Moon", "Bouncing across the lunar surface",
                  "Айда", "Айдын бетинде секирет"),
    "spaceship": ("On the bridge", "At the helm of a starship",
                  "Кеме рубкасында", "Жылдыз кемесин башкарат"),
    "alien-meet": ("Meeting an alien", "Meets a friendly alien",
                   "Келгин менен таанышуу", "Боорукер келгин менен таанышат"),
    "takes-off": ("Lift-off", "Leaves the ground and rises",
                  "Учуу", "Жерден көтөрүлүп жогору кетет"),
    "flying": ("Flight over the city", "Flying through the clouds",
               "Шаардын үстүнөн учуу", "Булуттардын арасынан учат"),
    "chase": ("The chase", "Racing through the streets",
              "Кууп жетүү", "Көчөлөр менен чуркайт"),
    "battle": ("The fight", "Facing a huge robot",
               "Салгылашуу", "Чоң роботко каршы турат"),
    "dino-meets": ("Meeting a dinosaur", "Meets a friendly dinosaur",
                   "Динозавр менен таанышуу", "Боорукер динозавр менен таанышат"),
    "funny-fall": ("A funny tumble", "Trips and gets back up",
                   "Күлкүлүү жыгылуу", "Мүдүрүлүп жыгылып, туруп кетет"),
    "dance": ("Dance", "Going all in to the music",
              "Бий", "Музыканын коштоосунда бийлейт"),
    "cake-face": ("Cake in the face", "Catches a cake with their face",
                  "Бетке торт", "Тортту бети менен кармайт"),
    "sleepy": ("Falling asleep on the go", "Nods off into the pillows",
               "Басып баратып уктап калат", "Көзү илинип, жаздыкка жыгылат"),
    "football": ("Goal!", "Scores the decisive goal",
                 "Гол!", "Чечүүчү голду киргизет"),
    "skate": ("Skate trick", "Flying off the ramp",
              "Скейт трюгу", "Рампадан учуп чыгат"),
    "finish-line": ("The finish", "Crossing the finish line",
                    "Финиш", "Финиш тасмасын кесип өтөт"),
    "goes-home": ("Going home", "Walking away at sunset",
                  "Үйгө кайтуу", "Күн батканда кетип баратат"),
    "group-hug": ("All together", "Hugging their friends",
                  "Баары чогуу", "Досторун кучактайт"),
    "stars-wish": ("Making a wish", "Watching a falling star",
                   "Тилек айтуу", "Учуп бараткан жылдызды карайт"),
    "the-end": ("The end", "Waving goodbye",
                "Титрлер", "Коштошуп кол булгалайт"),
}
