"""Generate src/reconpilot_web/common_passwords.txt: well-known common passwords, then common patterns built from them.

Deterministic. Ordered roughly from most to least common; capped at 10,000 lines.
"""

import sys

TOP = """
123456 password 12345678 qwerty 123456789 12345 1234 111111 1234567 dragon 123123 baseball abc123
football monkey letmein 696969 shadow master 666666 qwertyuiop 123321 mustang 1234567890 michael
654321 superman 1qaz2wsx 7777777 121212 000000 qazwsx 123qwe killer trustno1 jordan jennifer zxcvbnm
asdfgh hunter buster soccer harley batman andrew tigger sunshine iloveyou 2000 charlie robert thomas
hockey ranger daniel starwars klaster 112233 george computer michelle jessica pepper 1111 zxcvbn
555555 11111111 131313 freedom 777777 pass maggie 159753 aaaaaa ginger princess joshua cheese amanda
summer love ashley nicole chelsea biteme matthew access yankees 987654321 dallas austin thunder taylor
matrix mobilemail mom monitor monitoring montana moon moscow welcome admin login passw0rd p@ssw0rd
p@ssword password1 password12 password123 password1234 qwerty123 qwerty1 1q2w3e4r 1q2w3e4r5t
1q2w3e 1qazxsw2 zaq12wsx zaq1zaq1 qwe123 asdf1234 asdfghjkl qwert 123abc abcd1234 abcdef abc123456
iloveyou1 princess1 sunshine1 football1 monkey1 charlie1 aa123456 password! welcome1 welcome123
admin123 administrator root toor guest default changeme secret letmein1 starwars1 dragon1 master1
hello hello123 hellokitty whatever trustme blink182 flower flowers lovely loveme babygirl angel angels
butterfly purple jordan23 lakers liverpool arsenal manchester chocolate cookie cookies banana orange
apple pokemon naruto minecraft fortnite superstar rockstar michael1 jessica1 ashley1 nicole1 daniel1
anthony 666666666 777777777 888888 88888888 999999 99999999 222222 333333 444444 0000 00000000
1111111 11111 123 12 123654 147258369 147258 963852741 741852963 159357 789456123 789456 456789
123789 321654 987654 9876543210 0123456789 01234567 1234qwer qwer1234 q1w2e3r4 q1w2e3r4t5 1a2b3c4d
a1b2c3d4 a1b2c3 abc12345 test test123 test1234 testing user user123 demo sample pass123 pass1234
passpass mypassword yourpassword newpassword oldpassword thepassword password2 password3 secret123
""".split()

WORDS = """
password qwerty dragon monkey letmein shadow master killer hunter buster soccer harley batman andrew
tigger sunshine charlie robert thomas hockey ranger daniel starwars george computer michelle jessica
pepper freedom maggie ginger princess joshua cheese amanda summer love ashley nicole chelsea matthew
access yankees dallas austin thunder taylor matrix welcome admin login hello flower lovely angel
butterfly purple lakers liverpool arsenal chocolate cookie banana orange apple pokemon naruto
minecraft superstar rockstar anthony secret default guest football baseball basketball soccer
iloveyou loveyou forever family friends friend happy smile lucky money diamond silver golden gold
winter spring autumn spider spiderman ironman captain america canada london paris france germany
england india china japan mexico brazil london chicago boston texas florida california newyork
miami vegas tiger lion eagle falcon wolf panther cobra viper phoenix snake shark dolphin horse
puppy kitty kitten doggy bear teddy bunny monkey1 cowboy cowboys steelers packers patriots giants
eagles bears broncos raiders yankees redsox dodgers rangers celtics bulls warriors chelsea
barcelona realmadrid juventus milan bayern united city spurs everton tottenham rangers celtic
mercedes ferrari porsche corvette camaro mustang honda toyota nissan yamaha suzuki harley ducati
bmw audi volvo jaguar jeep dodge ford chevy subaru tesla google facebook twitter youtube instagram
apple samsung nokia sony nintendo xbox playstation gamer gaming hacker matrix linux windows
microsoft internet online network server system security private public office work company
business manager director student school college teacher doctor nurse police soldier army navy
pilot captain king queen prince princess knight wizard magic dragon ninja samurai warrior hero
legend master killer slayer hunter shooter sniper ghost demon devil angel heaven hell jesus christ
god lord bible church faith hope grace peace trinity blessed praise savior amen holy spirit
music guitar piano drums singer dancer rocknroll metallica nirvana beatles eminem shakira
beyonce rihanna madonna elvis marley bob cool crazy sexy hot baby honey sweet sweetie sugar candy
cupcake muffin pumpkin peanut butter coffee pizza pasta bacon burger hotdog chicken cheese tomato
potato carrot cherry strawberry lemon mango peach melon grape blueberry rainbow sunset sunrise
ocean river mountain forest island beach desert storm thunder lightning fire water earth wind
sky star stars moon planet galaxy universe space rocket jupiter mars venus saturn mercury
red blue green yellow black white pink orange brown gray grey violet silver
monday tuesday wednesday thursday friday saturday sunday january february march april may june
july august september october november december christmas easter halloween birthday holiday
michael christopher matthew joshua david james daniel robert john joseph andrew ryan brandon
jason justin william jonathan nicholas anthony kevin steven thomas brian eric charles timothy
richard jeremy jeffrey mark paul adam scott patrick sean benjamin aaron kyle jacob alexander
tyler zachary samuel nathan peter frank jack harry oliver george charlie henry edward alfie
jennifer jessica amanda ashley sarah stephanie melissa nicole elizabeth heather tiffany michelle
amber megan rachel amy kimberly christina lauren crystal brittany rebecca laura danielle emily
samantha angela erin kelly sara lisa katherine andrea jamie mary maria anna emma olivia sophia
isabella charlotte amelia mia grace chloe lily ella hannah victoria natalie alexis jasmine
abigail madison alice julia diana linda susan karen nancy betty helen sandra donna carol
ruth sharon dorothy patricia barbara margaret jordan taylor morgan casey alex sam chris pat
mike dave steve tom tony nick joe jim bill bob rick matt josh dan ben max jake luke mark
buddy rocky lucky bailey max molly bella daisy lucy sadie maggie sophie chloe coco oscar milo
toby jack duke bear tucker zeus rex spot fluffy smokey shadow princess sammy simba nala
oreo ginger pepper muffin peanut biscuit scooby snoopy garfield tweety mickey minnie donald
goofy pluto barbie elmo pooh winnie tigger bambi dumbo nemo shrek simpson homer bart
superman batman spiderman ironman hulk thor loki wolverine deadpool joker harley venom
starwars jedi yoda vader skywalker solo chewbacca matrix neo trinity morpheus gandalf frodo
hobbit potter harrypotter hermione voldemort dumbledore hogwarts narnia avatar zelda mario
luigi sonic pikachu pacman tetris halo doom quake counter strike warcraft diablo starcraft
fifa madden tekken mortal kombat street fighter
qwertyuiop asdfghjkl zxcvbnm qwertyui asdfghjk zxcvbn qazwsx wsxedc edcrfv rfvtgb tgbyhn
yhnujm ujmik qweasd asdzxc qweasdzxc zaqxsw 1qaz 2wsx 3edc 4rfv 1qaz2wsx3edc qazxswedc
poiuytrewq lkjhgfdsa mnbvcxz qwertz azerty asdfgh qweasdzxc qwerasdf asdfqwer
trustno1 letmein access shadow master mustang superman batman football baseball dragon
monkey killer charlie jordan hunter ranger buster soccer harley hockey thomas tigger robert
""".split()

SUFFIXES = [
    "", "1", "12", "123", "1234", "12345", "123456", "!", "1!", "123!", "01", "007", "69", "99", "2",
    "11", "13", "22", "23", "7", "77", "777", "88", "00", "@123", "#1", "!!", "?", ".", "*",
    "2020", "2021", "2022", "2023", "2024", "2025", "2026", "2019", "2018", "2010", "2000",
    "1990", "1985", "1980", "1995", "1999", "1234!", "12345!", "2024!", "2025!", "2026!",
]

LEET = str.maketrans({"a": "@", "o": "0", "e": "3", "i": "1", "s": "$"})


def keyboard_runs() -> list[str]:
    rows = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm", "0987654321", "poiuytrewq"]
    out = []
    for row in rows:
        for length in range(4, len(row) + 1):
            out.append(row[:length])
    return out


def repeats() -> list[str]:
    out = []
    for ch in "0123456789abcdefghijklmnopqrstuvwxyz":
        for length in range(4, 17):
            out.append(ch * length)
    for chunk in ("12", "123", "1234", "abc", "ab", "69", "qwe", "asd", "xo", "ha", "la"):
        for times in range(2, 7):
            out.append(chunk * times)
    return out


def dates() -> list[str]:
    out = [str(y) for y in range(1950, 2031)]
    for y in range(1960, 2027):
        out.append(f"0101{y}")
        out.append(f"{y}0101")
    return out


def main(path: str) -> None:
    seen: dict[str, None] = {}

    def add(word: str) -> None:
        w = word.strip().lower()
        if len(w) >= 3 and w not in seen:
            seen[w] = None

    for w in TOP:
        add(w)
    for w in keyboard_runs():
        add(w)
    for w in repeats():
        add(w)
    for w in dates():
        add(w)
    words = list(dict.fromkeys(w.lower() for w in WORDS))
    # Patterns in rounds so the most common forms of every word come before rarer forms of any.
    for suffix in SUFFIXES:
        for w in words:
            add(w + suffix)
        if suffix in ("", "1", "123", "!"):
            for w in words:
                add(w.translate(LEET) + suffix)
    for w in words:
        add("my" + w)
        add("ilove" + w)
        add(w + w)
        add(w + "123456789")
    lines = list(seen)[:10000]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print(len(lines), "lines; total candidates", len(seen))


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1].startswith("-"):
        sys.exit("usage: python scripts/gen_common_passwords.py OUTPUT_FILE")
    main(sys.argv[1])
