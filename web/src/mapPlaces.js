// Généré par scripts/build_map_places.py : position (u, v de 0 à 1, v vers le bas) des lieux sur
// web/decor/carte_herisson_1815.jpg. region : null = toujours affiché, sinon région de l'archiviste.
export const MAP_PLACES = [
  {
    "name": "Paris",
    "u": 0.285,
    "v": 0.3566,
    "region": null
  },
  {
    "name": "Londres",
    "u": 0.2846,
    "v": 0.2566,
    "region": null
  },
  {
    "name": "Madrid",
    "u": 0.1252,
    "v": 0.5714,
    "region": null
  },
  {
    "name": "Lisbonne",
    "u": 0.0479,
    "v": 0.5611,
    "region": null
  },
  {
    "name": "Rome",
    "u": 0.4124,
    "v": 0.6097,
    "region": null
  },
  {
    "name": "Vienne",
    "u": 0.4932,
    "v": 0.4343,
    "region": null
  },
  {
    "name": "Berlin",
    "u": 0.4596,
    "v": 0.2971,
    "region": null
  },
  {
    "name": "Varsovie",
    "u": 0.5614,
    "v": 0.3165,
    "region": null
  },
  {
    "name": "Moscou",
    "u": 0.7803,
    "v": 0.1703,
    "region": null
  },
  {
    "name": "Constantinople",
    "u": 0.6915,
    "v": 0.6349,
    "region": null
  },
  {
    "name": "Le Caire",
    "u": 0.7628,
    "v": 0.96,
    "region": null
  },
  {
    "name": "Ajaccio",
    "u": 0.3489,
    "v": 0.5964,
    "region": "corse"
  },
  {
    "name": "Toulon",
    "u": 0.3076,
    "v": 0.5481,
    "region": "france"
  },
  {
    "name": "Fontainebleau",
    "u": 0.287,
    "v": 0.3724,
    "region": "france"
  },
  {
    "name": "Milan",
    "u": 0.3723,
    "v": 0.4927,
    "region": "italie"
  },
  {
    "name": "Lodi",
    "u": 0.3766,
    "v": 0.4984,
    "region": "italie"
  },
  {
    "name": "Arcole",
    "u": 0.405,
    "v": 0.5034,
    "region": "italie"
  },
  {
    "name": "Rivoli",
    "u": 0.3985,
    "v": 0.4956,
    "region": "italie"
  },
  {
    "name": "Marengo",
    "u": 0.3616,
    "v": 0.5079,
    "region": "italie"
  },
  {
    "name": "Alexandrie",
    "u": 0.7073,
    "v": 0.9314,
    "region": "egypte"
  },
  {
    "name": "Aboukir",
    "u": 0.7104,
    "v": 0.9274,
    "region": "egypte"
  },
  {
    "name": "Les Pyramides",
    "u": 0.7604,
    "v": 0.9622,
    "region": "egypte"
  },
  {
    "name": "Saint-Jean-d'Acre",
    "u": 0.8282,
    "v": 0.8686,
    "region": "egypte"
  },
  {
    "name": "Saragosse",
    "u": 0.1846,
    "v": 0.5536,
    "region": "espagne"
  },
  {
    "name": "Baylen",
    "u": 0.1072,
    "v": 0.638,
    "region": "espagne"
  },
  {
    "name": "Ulm",
    "u": 0.3969,
    "v": 0.4084,
    "region": "autriche"
  },
  {
    "name": "Austerlitz",
    "u": 0.5006,
    "v": 0.4067,
    "region": "autriche"
  },
  {
    "name": "Wagram",
    "u": 0.4961,
    "v": 0.4319,
    "region": "autriche"
  },
  {
    "name": "Iéna",
    "u": 0.4298,
    "v": 0.3389,
    "region": "prusse"
  },
  {
    "name": "Eylau",
    "u": 0.5568,
    "v": 0.2518,
    "region": "pologne"
  },
  {
    "name": "Friedland",
    "u": 0.5616,
    "v": 0.25,
    "region": "pologne"
  },
  {
    "name": "Leipzig",
    "u": 0.4422,
    "v": 0.3293,
    "region": "allemagne"
  },
  {
    "name": "Dresde",
    "u": 0.4609,
    "v": 0.3424,
    "region": "allemagne"
  },
  {
    "name": "Smolensk",
    "u": 0.7073,
    "v": 0.2223,
    "region": "russie"
  },
  {
    "name": "La Moskowa",
    "u": 0.7562,
    "v": 0.1858,
    "region": "russie"
  },
  {
    "name": "Bérézina",
    "u": 0.6644,
    "v": 0.2455,
    "region": "russie"
  },
  {
    "name": "Waterloo",
    "u": 0.3274,
    "v": 0.3134,
    "region": "belgique"
  },
  {
    "name": "Ligny",
    "u": 0.3287,
    "v": 0.3195,
    "region": "belgique"
  },
  {
    "name": "Portoferraio",
    "u": 0.38,
    "v": 0.5757,
    "region": "elbe"
  }
]

// Calage de la carte (même calcul que to_uv) : polynôme du second degré en (longitude, latitude),
// puis écart des repères réparti en inverse du carré de la distance.
export const MAP_FIT = {"cx": [120.78089819597976, 67.51716459980427, 24.855981713684134, 0.10102781244966152, -0.07591374568811915, -0.7549805648745007], "cy": [4057.664228847096, 12.025915743628955, -52.54760565900445, -0.2840498971912506, 0.001784105974708794, 0.006187432533514947], "crop": [540, 900, 2880, 2650], "control": [[2.35, 48.86, -19.55094947517614, 2.1499045408609163], [-0.13, 51.5, 10.199204696710922, -5.584838129042282], [-3.7, 40.42, -32.913518054642964, 12.70504828237813], [-9.14, 38.72, 24.087127981386857, -7.859715905673056], [12.5, 41.9, 11.699316728380836, -1.2335641737258811], [16.37, 48.21, 14.851083212810863, 5.880676199324398], [37.62, 55.75, -4.101947720845601, 0.9334357454699784], [28.98, 41.01, 1.3254875095090028, -11.99550173904754], [31.24, 30.04, 26.72824289689197, -5.025361408745994], [29.92, 31.2, -33.166982936756995, -1.2237585903731087], [35.07, 32.93, 0.8429351619806766, 11.25367517865834]]}
