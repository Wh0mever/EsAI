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
KIDS_CATEGORIES = [
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


# ===========================================================================
# Взрослая половина библиотеки
# ===========================================================================
# Клиент: «сейчас библиотека слишком ориентирована на детские мультфильмы»,
# нужны взрослые герои и серьёзные разделы, из которых собирается не набор
# гэгов, а короткометражка. Отсюда два отличия от детской половины.
#
# Первое — стиль. Тот же милый Pixar-рендер на сцене допроса или ссоры
# выглядит пародией, поэтому у взрослых сцен своя подача: сдержанный цвет,
# киносвет, почти реалистичные пропорции.
#
# Второе — разделы названы по жанру истории, а не по её этапу. Взрослую
# короткометражку собирают из «детектива» и «драмы», а не из «начала» и
# «финала», и человек ищет сцену именно так.

ADULT_STYLE = (
    "stylized 3D animated film style, semi-realistic adult proportions, "
    "cinematic film lighting, muted filmic color grading, shallow depth of field, "
    "detailed textures, dramatic composition, adult animated feature look, "
    "NOT childish, NOT toy-like"
)

# (код, название, значок, порядок)
ADULT_CATEGORIES = [
    ("city", "Городская жизнь", "🌆", 110),
    ("office", "Офис и бизнес", "💼", 120),
    ("relationships", "Отношения", "❤️", 130),
    ("family", "Семья", "🏡", 140),
    ("travel", "Путешествия", "✈️", 150),
    ("detective", "Детектив", "🕵️", 160),
    ("drama", "Драма", "🎭", 170),
    ("crime", "Криминал", "🚔", 180),
    ("thriller", "Экшен и погони", "💥", 190),
    ("fantasy", "Фэнтези", "🐉", 200),
    ("scifi", "Научная фантастика", "🛸", 210),
]

# (имя, описание для моделей, как рисовать, раздел)
# Типажи специально разные по полу, возрасту и внешности: клиент просил, чтобы
# в библиотеке узнавал себя не только ребёнок.
ADULT_CHARACTERS = [
    ("Бизнесвумен",
     "a confident woman in her thirties in a dark tailored suit",
     "a confident businesswoman in her mid-thirties, dark tailored suit, short black bob haircut, "
     "East Asian features, calm determined expression",
     "office"),
    ("Молодой предприниматель",
     "a young man in his late twenties in a white shirt with rolled sleeves",
     "a young entrepreneur in his late twenties, white shirt with rolled-up sleeves, light stubble, "
     "brown wavy hair, warm friendly face",
     "office"),
    ("Детектив",
     "a weathered man in his forties in a long dark coat",
     "a weathered detective in his mid-forties, long dark coat, grey-streaked hair, tired sharp eyes, "
     "unshaven, Central Asian features",
     "detective"),
    ("Журналистка",
     "a woman in her early thirties with a camera on her shoulder",
     "a journalist in her early thirties, dark curly hair, denim jacket, camera strap over the shoulder, "
     "Black woman, curious alert expression",
     "city"),
    ("Бариста",
     "a young man in an apron with tattooed forearms",
     "a barista in his mid-twenties, canvas apron over a t-shirt, tattooed forearms, undercut hairstyle, "
     "easygoing smile",
     "city"),
    ("Врач",
     "a woman doctor in her forties in a white coat",
     "a doctor in her forties, white coat over blue scrubs, hair tied back, glasses, "
     "Latina features, calm reassuring face",
     "drama"),
    ("Таксист",
     "a heavyset man in his fifties in a worn jacket",
     "a heavyset taxi driver in his fifties, worn leather jacket, moustache, thinning grey hair, "
     "kind lived-in face",
     "crime"),
    ("Студентка",
     "a young woman in her early twenties with a backpack and headphones",
     "a student in her early twenties, oversized hoodie, backpack, headphones around the neck, "
     "long dark hair, Central Asian features",
     "travel"),
    ("Профессор",
     "an elderly man in his sixties in a cardigan and round glasses",
     "an elderly professor in his mid-sixties, knitted cardigan, round glasses, white beard, "
     "thoughtful gentle expression",
     "scifi"),
    ("Молодая мама",
     "a woman in her early thirties in a soft knitted sweater",
     "a young mother in her early thirties, soft knitted sweater, hair in a loose bun, "
     "warm tired smile, freckles",
     "family"),
]

# (код, название, подпись, промпт сцены, промпт движения, длительность, раздел)
ADULT_PRESETS = [
    # --- Городская жизнь ---
    ("city-night-walk", "Ночная улица", "Идёт под неоном после дождя",
     "the character walks alone along a wet night city street, neon signs reflected in puddles, "
     "steam rising from a grate, few passers-by in the background",
     "slow tracking shot alongside the character, neon reflections shimmer, light rain drifts", 5, "city"),
    ("city-cafe", "Кофе у окна", "Сидит с чашкой и смотрит на улицу",
     "the character sits alone at a cafe window table with a cup of coffee, city street blurred outside, "
     "warm interior light, rain on the glass",
     "camera slowly pushes in, steam curls from the cup, the character looks out at the street", 5, "city"),
    ("city-metro", "В метро", "Стоит в вагоне, отражение в стекле",
     "the character stands in a moving subway car holding the rail, tired commuters around, "
     "own reflection visible in the dark window",
     "the car sways, tunnel lights flash past the window, the character's gaze drifts", 5, "city"),
    ("city-rooftop", "На крыше вечером", "Смотрит на город сверху",
     "the character stands at the edge of a rooftop above a glowing evening city, "
     "skyline stretching to the horizon, wind moving their clothes",
     "slow crane shot rising behind the character, city lights twinkle below", 5, "city"),

    # --- Офис и бизнес ---
    ("office-pitch", "Питч", "Выступает перед командой у экрана",
     "the character presents to a small team in a glass meeting room, charts on the screen behind, "
     "colleagues listening around the table",
     "camera arcs slowly around the character, they gesture at the screen, colleagues lean in", 5, "office"),
    ("office-late", "Поздно в офисе", "Один за ноутбуком ночью",
     "the character works alone late at night in a dark open-plan office, only the desk lamp and "
     "laptop screen lit, empty desks around, city lights in the windows",
     "camera drifts closer, screen light flickers on the face, the character rubs their eyes", 5, "office"),
    ("office-handshake", "Сделка", "Рукопожатие в переговорной",
     "the character shakes hands with a business partner across a meeting room table, "
     "signed documents between them, daylight through tall windows",
     "the handshake holds, camera pushes in on the joined hands then rises to the faces", 5, "office"),
    ("office-quit", "Уходит из офиса", "С коробкой вещей идёт по опенспейсу",
     "the character walks out through an open-plan office carrying a cardboard box of personal things, "
     "colleagues watching from their desks",
     "steady tracking shot backwards ahead of the character walking, heads turn as they pass", 5, "office"),

    # --- Отношения ---
    ("rel-first-date", "Первое свидание", "Двое за столиком при свечах",
     "the character sits across a small restaurant table from a companion, candle between them, "
     "warm low light, wine glasses, both slightly nervous and smiling",
     "camera slowly circles the table, candle flame flickers, the character laughs softly", 5, "relationships"),
    ("rel-argument", "Ссора", "Отворачивается, напряжение в комнате",
     "the character stands turned away in a dim apartment room after an argument, "
     "another person out of focus in the background, cold evening light from the window",
     "camera holds still, the character's shoulders rise with a breath, then they turn their head", 5, "relationships"),
    ("rel-reunion", "Встреча в аэропорту", "Обнимает встречающего",
     "the character embraces someone in a bright airport arrivals hall, suitcase dropped beside them, "
     "crowd of travellers blurred around",
     "camera pushes in through the crowd, the embrace tightens, people pass in soft focus", 5, "relationships"),
    ("rel-goodbye", "Прощание на перроне", "Машет вслед уходящему поезду",
     "the character stands alone on a railway platform waving after a departing train, "
     "evening light, empty platform stretching away",
     "the train pulls out of frame, the character's hand slowly lowers, camera drifts back", 5, "relationships"),

    # --- Семья ---
    ("fam-dinner", "Семейный ужин", "За большим столом со своими",
     "the character sits at a crowded family dinner table, dishes and warm lamplight, "
     "relatives talking and laughing around",
     "camera drifts along the table, the character laughs and passes a dish", 5, "family"),
    ("fam-morning", "Утро на кухне", "Готовит завтрак у плиты",
     "the character makes breakfast in a sunlit home kitchen, pan on the stove, coffee brewing, "
     "morning light across the counter",
     "steam rises from the pan, the character moves easily around the kitchen, camera follows", 5, "family"),
    ("fam-park", "Прогулка в парке", "Идёт за руку с ребёнком",
     "the character walks through an autumn park holding a small child's hand, "
     "golden leaves on the path, low warm sun through the trees",
     "steady tracking shot from the side, leaves drift down, the two walk unhurried", 5, "family"),
    ("fam-old-photos", "Старые фотографии", "Разглядывает семейный альбом",
     "the character sits on a couch looking through an old family photo album, "
     "soft lamp light, framed pictures on the shelf behind",
     "camera slowly pushes in over the shoulder, a page turns, the character smiles faintly", 5, "family"),

    # --- Путешествия ---
    ("trav-airport", "В аэропорту", "С чемоданом у табло вылетов",
     "the character stands with a suitcase looking up at a departures board in a busy airport terminal, "
     "travellers streaming past, wide bright hall",
     "the board flickers to a new row, crowds blur past, the character adjusts the bag strap", 5, "travel"),
    ("trav-road", "Дорога на закате", "За рулём по пустой трассе",
     "the character drives along an empty highway at sunset, hand on the wheel, "
     "endless road ahead, orange sky and long shadows",
     "camera rides beside the car, the landscape streams past, sunlight strobes across the face", 5, "travel"),
    ("trav-mountains", "В горах", "Смотрит на горную панораму",
     "the character stands on a mountain ridge looking out over vast peaks and valleys, "
     "backpack on, cold clear air, clouds below the summit",
     "slow crane shot rising behind the character, clouds roll through the valley", 5, "travel"),
    ("trav-market", "Восточный базар", "Идёт вдоль пёстрых прилавков",
     "the character walks through a bustling oriental bazaar, stalls of spices and fabrics, "
     "hanging lamps, sunlight through canvas awnings",
     "handheld tracking shot following the character, traders gesture, fabric sways", 5, "travel"),

    # --- Детектив ---
    ("det-board", "Доска с уликами", "Изучает стену с фотографиями и нитями",
     "the character studies an evidence board covered with photographs and red string in a dim room, "
     "single desk lamp, notes pinned everywhere",
     "camera pushes slowly toward the board past the character, they pin one more photo", 5, "detective"),
    ("det-rain-street", "Слежка", "Стоит под дождём у фонаря",
     "the character waits under a streetlamp in the rain watching a lit doorway across the street, "
     "collar up, wet asphalt reflecting the light",
     "rain streaks through the lamplight, the character shifts, headlights sweep past", 5, "detective"),
    ("det-interrogation", "Допрос", "За столом под низкой лампой",
     "the character sits at a bare table under a low hanging lamp in an interrogation room, "
     "harsh light pool, dark walls beyond",
     "camera slowly lowers to eye level, the character leans forward into the light", 5, "detective"),
    ("det-clue", "Улика", "Рассматривает находку в свете фонарика",
     "the character examines a small object in the beam of a flashlight in a dark room, "
     "dust in the light, gloved hand holding the find",
     "the flashlight beam trembles slightly, the object turns in the hand, camera pushes in", 5, "detective"),

    # --- Драма ---
    ("dra-rain-window", "У окна под дождём", "Смотрит, как за стеклом идёт дождь",
     "the character stands at a window watching heavy rain, room dim behind them, "
     "grey daylight, raindrops running down the glass",
     "rain runs down the glass, the character's reflection wavers, camera drifts closer", 5, "drama"),
    ("dra-empty-room", "Пустая комната", "Сидит на полу среди коробок",
     "the character sits on the floor of an almost empty apartment among moving boxes, "
     "bare walls, late afternoon light across the floorboards",
     "camera slowly pulls back revealing the empty room around the character", 5, "drama"),
    ("dra-confession", "Признание", "Говорит, глядя прямо перед собой",
     "close portrait of the character speaking quietly to someone off camera, "
     "soft side light, plain dark background, raw honest expression",
     "very slow push-in on the face, the character swallows and keeps talking", 5, "drama"),
    ("dra-hospital", "Больничный коридор", "Ждёт на скамейке под лампами",
     "the character waits alone on a bench in a long empty hospital corridor at night, "
     "cold fluorescent light, closed doors receding into the distance",
     "camera holds far away then drifts in, a door opens somewhere down the corridor", 5, "drama"),

    # --- Криминал ---
    ("cri-alley", "Тёмный переулок", "Идёт между стен в темноте",
     "the character walks down a narrow dark alley between brick walls, "
     "single flickering lamp, fire escapes above, fog low on the ground",
     "camera tracks behind the character, the lamp flickers, a shadow moves ahead", 5, "crime"),
    ("cri-briefcase", "Передача", "Обмен чемоданом на парковке",
     "the character hands a metal briefcase to another figure on an empty underground parking level, "
     "concrete pillars, harsh overhead lights, car headlights behind",
     "the case changes hands, both glance around, headlights sweep across the pillars", 5, "crime"),
    ("cri-police-lights", "Мигалки", "Стоит в свете полицейских огней",
     "the character stands still in the flashing blue and red lights of police cars at night, "
     "wet street, silhouettes of officers behind the glare",
     "the lights pulse across the face, the character slowly raises their head", 5, "crime"),
    ("cri-escape", "Уходит от погони", "Взбирается по пожарной лестнице",
     "the character climbs a rusty fire escape up the side of a night building, "
     "city glow below, looking back over the shoulder",
     "the character climbs fast, camera rises alongside, city lights spread out below", 5, "crime"),

    # --- Экшен и погони ---
    ("thr-car-chase", "Погоня на машине", "За рулём на предельной скорости",
     "the character grips the wheel driving fast through night city streets, "
     "headlights streaking past, tense focused face lit by dashboard glow",
     "the car swerves, streetlights strobe across the face, camera shakes with the road", 5, "thriller"),
    ("thr-rooftop-run", "Бег по крышам", "Прыгает через пролёт между домами",
     "the character sprints across rooftops and leaps a gap between buildings, "
     "city sprawling below, dusk sky behind",
     "camera tracks the run and follows the leap in a wide arc, coat flying", 5, "thriller"),
    ("thr-standoff", "Противостояние", "Стоит напротив противника",
     "the character stands facing an opponent across an empty warehouse, both still, "
     "shafts of light through high windows, dust in the air",
     "camera circles slowly between the two figures, dust drifts through the light", 5, "thriller"),
    ("thr-explosion", "Уходит от взрыва", "Идёт, не оборачиваясь на огонь",
     "the character walks away from a burning wreck without looking back, "
     "fire and smoke filling the background, embers in the air",
     "the character walks steadily toward camera, flames roar behind, embers drift past", 5, "thriller"),

    # --- Фэнтези ---
    ("fan-throne", "Тронный зал", "Входит в древний зал",
     "the character walks into a vast ancient throne hall with towering stone columns, "
     "shafts of light from high windows, banners hanging in the gloom",
     "camera pulls back ahead of the character revealing the scale of the hall", 5, "fantasy"),
    ("fan-sword", "Клинок", "Обнажает меч в тумане",
     "the character draws a sword in thick morning fog on an open field, "
     "cold pale light, dew on the grass, blade catching the light",
     "the blade slides free with a glint, fog swirls around the character", 5, "fantasy"),
    ("fan-ancient-forest", "Древний лес", "Идёт среди исполинских деревьев",
     "the character walks a narrow path between colossal ancient trees, "
     "moss and ferns everywhere, green light filtering from far above",
     "camera cranes up along a huge trunk as the character walks below", 5, "fantasy"),
    ("fan-portal", "Портал", "Стоит перед светящимся кругом рун",
     "the character stands before a glowing circle of runes floating in a dark stone chamber, "
     "magical light washing over them, symbols slowly rotating",
     "the runes rotate and brighten, light pulses over the character, they step forward", 5, "fantasy"),

    # --- Научная фантастика ---
    ("sci-neon-city", "Неоновый мегаполис", "Стоит среди летающих машин",
     "the character stands on a walkway high above a neon megacity, flying vehicles streaming past, "
     "holographic billboards, rain-slick surfaces",
     "flying cars streak past, holograms shift, camera drifts along the walkway", 5, "scifi"),
    ("sci-lab", "Лаборатория", "Работает с голограммой",
     "the character studies a glowing holographic projection in a clean high-tech laboratory, "
     "blue light on the face, equipment humming around",
     "the hologram rotates under the character's hand, data panels flicker", 5, "scifi"),
    ("sci-station", "Орбитальная станция", "Смотрит на Землю в иллюминатор",
     "the character floats at a large viewport of an orbital station looking down at Earth, "
     "blue planet light on the face, stars beyond",
     "Earth slowly turns beyond the glass, light sweeps across the character's face", 5, "scifi"),
    ("sci-android", "Встреча с андроидом", "Стоит лицом к лицу с машиной",
     "the character stands face to face with a humanoid android in a dim corridor, "
     "the android's eyes glowing softly, reflective panels around",
     "the android tilts its head, light shifts between the two faces, camera pushes in", 5, "scifi"),
]

# --- Сведение обеих половин -------------------------------------------------
# Разделы носят пометку аудитории: 19 разделов одной строкой не читаются, и в
# студии человек сначала выбирает, для кого он снимает, а уже потом жанр.
CATEGORIES = ([(slug, title, emoji, order, "kids") for slug, title, emoji, order in KIDS_CATEGORIES]
              + [(slug, title, emoji, order, "adults") for slug, title, emoji, order in ADULT_CATEGORIES])

ADULT_CATEGORY_SLUGS = {slug for slug, _t, _e, _o in ADULT_CATEGORIES}

CHARACTERS = CHARACTERS + ADULT_CHARACTERS
PRESETS = PRESETS + ADULT_PRESETS


def audience_of(category_slug: str) -> str:
    """Для кого раздел. Взрослые сцены снимаются другим стилем и другим героем."""
    return "adults" if category_slug in ADULT_CATEGORY_SLUGS else "kids"


def style_for(category_slug: str) -> str:
    """Стиль кадра. Милый Pixar-рендер на сцене допроса выглядит пародией."""
    return ADULT_STYLE if audience_of(category_slug) == "adults" else STYLE


CATEGORY_TRANSLATIONS.update({
    "city": ("City life", "Шаардык турмуш"),
    "office": ("Office & business", "Офис жана бизнес"),
    "relationships": ("Relationships", "Мамилелер"),
    "family": ("Family", "Үй-бүлө"),
    "travel": ("Travel", "Саякат"),
    "detective": ("Detective", "Детектив"),
    "drama": ("Drama", "Драма"),
    "crime": ("Crime", "Кылмыш"),
    "thriller": ("Action & chases", "Экшен жана кубалоо"),
    "fantasy": ("Fantasy", "Фэнтези"),
    "scifi": ("Science fiction", "Илимий фантастика"),
})

CHARACTER_TRANSLATIONS.update({
    "Бизнесвумен": ("Businesswoman", "Ишкер аял"),
    "Молодой предприниматель": ("Young entrepreneur", "Жаш ишкер"),
    "Детектив": ("Detective", "Детектив"),
    "Журналистка": ("Journalist", "Журналист аял"),
    "Бариста": ("Barista", "Бариста"),
    "Врач": ("Doctor", "Дарыгер"),
    "Таксист": ("Taxi driver", "Таксист"),
    "Студентка": ("Student", "Студент кыз"),
    "Профессор": ("Professor", "Профессор"),
    "Молодая мама": ("Young mother", "Жаш эне"),
})

PRESET_TRANSLATIONS.update({
    "city-night-walk": ("Night street", "Walking under neon after rain",
                        "Түнкү көчө", "Жамгырдан кийин неон астында"),
    "city-cafe": ("Coffee by the window", "Sitting with a cup, watching the street",
                  "Терезе жанында кофе", "Чөйчөк менен отуруп көчөнү карайт"),
    "city-metro": ("On the subway", "Standing in the car, reflected in the glass",
                   "Метродо", "Вагондо турат, айнекте чагылышы"),
    "city-rooftop": ("Rooftop at dusk", "Looking down at the city",
                     "Кечинде чатырда", "Шаарды бийиктен карайт"),
    "office-pitch": ("The pitch", "Presenting to the team by the screen",
                     "Презентация", "Экран жанында командага сүйлөйт"),
    "office-late": ("Late at the office", "Alone with a laptop at night",
                    "Офисте кеч", "Түнкүсүн ноутбук менен жалгыз"),
    "office-handshake": ("The deal", "A handshake in the meeting room",
                         "Келишим", "Жыйын бөлмөсүндө кол алышуу"),
    "office-quit": ("Leaving the office", "Walking out with a box of things",
                    "Офистен кетүү", "Буюмдары салынган кутуча менен чыгат"),
    "rel-first-date": ("First date", "Two at a table by candlelight",
                       "Биринчи жолугушуу", "Шам жарыгында үстөл жанында экөө"),
    "rel-argument": ("The argument", "Turning away, tension in the room",
                     "Урушуу", "Бурулуп кетет, бөлмөдө чыңалуу"),
    "rel-reunion": ("Airport reunion", "An embrace in arrivals",
                    "Аэропортто жолугушуу", "Кучакташуу"),
    "rel-goodbye": ("Goodbye on the platform", "Waving after the leaving train",
                    "Перрондо коштошуу", "Кетип бараткан поездге кол булгайт"),
    "fam-dinner": ("Family dinner", "At the big table with everyone",
                   "Үй-бүлөлүк кечки тамак", "Чоң үстөлдө баары чогуу"),
    "fam-morning": ("Morning in the kitchen", "Making breakfast at the stove",
                    "Ашканада эртең менен", "Плита жанында эртең мененки тамак"),
    "fam-park": ("A walk in the park", "Holding a child's hand",
                 "Парктагы сейил", "Баланын колунан жетелеп"),
    "fam-old-photos": ("Old photographs", "Going through the family album",
                       "Эски сүрөттөр", "Үй-бүлөлүк альбомду карайт"),
    "trav-airport": ("At the airport", "With a suitcase at the departures board",
                     "Аэропортто", "Чемодан менен табло жанында"),
    "trav-road": ("The road at sunset", "Driving an empty highway",
                  "Кун батканда жол", "Ээн жолдо унаа айдап"),
    "trav-mountains": ("In the mountains", "Looking out over the peaks",
                       "Тоолордо", "Чокуларды карайт"),
    "trav-market": ("The bazaar", "Walking past the colourful stalls",
                    "Базар", "Түркүн текчелердин жанынан өтөт"),
    "det-board": ("The evidence board", "Studying photos and red string",
                  "Далилдер тактасы", "Сүрөттөр менен жиптерди изилдейт"),
    "det-rain-street": ("The stakeout", "Waiting under a lamp in the rain",
                        "Аңдуу", "Жамгырда чырак астында күтөт"),
    "det-interrogation": ("The interrogation", "At the table under a low lamp",
                          "Суракка алуу", "Төмөнкү чырак астында үстөлдө"),
    "det-clue": ("The clue", "Examining a find by flashlight",
                 "Далил", "Табылганы кол чырак менен карайт"),
    "dra-rain-window": ("By the rainy window", "Watching the rain behind the glass",
                        "Жамгырлуу терезе жанында", "Айнектин артындагы жамгырды карайт"),
    "dra-empty-room": ("The empty room", "Sitting on the floor among boxes",
                       "Бош бөлмө", "Куту-баштыктардын арасында полдо отурат"),
    "dra-confession": ("The confession", "Speaking quietly, straight ahead",
                       "Мойнуна алуу", "Тике карап акырын сүйлөйт"),
    "dra-hospital": ("Hospital corridor", "Waiting on a bench under the lights",
                     "Оорукана коридору", "Чырактардын астында отургучта күтөт"),
    "cri-alley": ("The dark alley", "Walking between the walls in the dark",
                  "Караңгы тар көчө", "Караңгыда дубалдардын ортосунда"),
    "cri-briefcase": ("The handover", "Trading a case in a car park",
                      "Өткөрүп берүү", "Унаа токтотуучу жайда чемодан алмашуу"),
    "cri-police-lights": ("Police lights", "Standing in the flashing glare",
                          "Полиция оттору", "Жаркыраган жарыкта турат"),
    "cri-escape": ("Getting away", "Climbing the fire escape",
                   "Качуу", "Өрт тепкичи менен жогору чыгат"),
    "thr-car-chase": ("The car chase", "At the wheel at full speed",
                      "Унаа кубалоо", "Ылдамдык менен рулда"),
    "thr-rooftop-run": ("Rooftop run", "Leaping the gap between buildings",
                        "Чатырлар боюнча чуркоо", "Үйлөрдүн ортосунан секирет"),
    "thr-standoff": ("The standoff", "Facing the opponent",
                     "Каршы туруу", "Атаандашка каршы турат"),
    "thr-explosion": ("Walking from the blast", "Not looking back at the fire",
                      "Жарылуудан кетүү", "Отко кылчайбайт"),
    "fan-throne": ("The throne hall", "Entering the ancient hall",
                   "Тактынын залы", "Байыркы залга кирет"),
    "fan-sword": ("The blade", "Drawing a sword in the fog",
                  "Кылыч", "Тумандын ичинде кылыч сууруйт"),
    "fan-ancient-forest": ("The ancient forest", "Walking among colossal trees",
                           "Байыркы токой", "Алп дарактардын арасында"),
    "fan-portal": ("The portal", "Facing a glowing ring of runes",
                   "Портал", "Жаркыраган руна тегерегинин алдында"),
    "sci-neon-city": ("Neon megacity", "Above the streams of flying cars",
                      "Неон мегаполис", "Учуучу унаалардын үстүндө"),
    "sci-lab": ("The laboratory", "Working with a hologram",
                "Лаборатория", "Голограмма менен иштейт"),
    "sci-station": ("Orbital station", "Looking at Earth through the viewport",
                    "Орбиталык станция", "Иллюминатордон Жерди карайт"),
    "sci-android": ("Meeting the android", "Face to face with the machine",
                    "Андроид менен жолугушуу", "Машина менен бетме-бет"),
})
