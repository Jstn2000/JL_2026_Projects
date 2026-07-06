from PIL import Image
import PIL

img = Image.open("E:/gta/cars/bin/ai/windows/random/ass3.jpg")
image_size:list[int] = img.size
pixel_size:int = 5
# print(type(img))

small_image = img.resize((int(image_size[0]/pixel_size), int(image_size[1]/pixel_size)), resample=Image.Resampling.BILINEAR)
pixel_art = small_image.resize(image_size, resample=Image.Resampling.NEAREST)

pixel_art.save("pixel_art_image.png")