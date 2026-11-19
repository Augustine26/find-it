from PIL import Image, ImageDraw, ImageFilter

def make(size=512):
    S = size
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # gradient rounded square (Fluent blue)
    grad = Image.new("RGBA", (S, S))
    gp = grad.load()
    for y in range(S):
        for x in range(S):
            t = (x + y) / (2 * S)
            gp[x, y] = (int(0 + 70 * t), int(120 - 20 * t), int(215 + 40 * t), 255)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((S*.04, S*.04, S*.96, S*.96), radius=S*.22, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # magnifier
    cx, cy, r = S*.44, S*.44, S*.21
    w = int(S*.075)
    d.ellipse((cx-r, cy-r, cx+r, cy+r), outline="white", width=w)
    d.line((cx+r*.72, cy+r*.72, S*.76, S*.76), fill="white", width=w)
    d.ellipse((S*.76-w/2, S*.76-w/2, S*.76+w/2, S*.76+w/2), fill="white")
    # file lines inside lens
    for i, f in enumerate((.9, .65)):
        y = cy - r*.25 + i*r*.5
        d.rounded_rectangle((cx-r*.5, y-w*.25, cx-r*.5 + r*f, y+w*.25), radius=w, fill=(255,255,255,230))
    return img

if __name__ == "__main__":
    im = make()
    im.save("findit.png")
    im.save("findit.ico", sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(24,24),(16,16)])
    print("icon ok")
