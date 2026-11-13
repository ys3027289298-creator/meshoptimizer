// This file is part of gltfpack; see gltfpack.h for version/license details
#ifdef WITH_LIBAVIF
#include "gltfpack.h"

#include "avif/avif.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Minimal self-contained PNG writer: AVIF decode always produces 8-bit RGBA, and using stored
// (uncompressed) DEFLATE blocks keeps the temporary file free of extra dependencies. The file is
// only consumed once by the BasisU/WebP encoders and is removed immediately afterwards.

static uint32_t crc32Update(uint32_t crc, const unsigned char* data, size_t size)
{
	static uint32_t table[256];
	static bool initialized = false;

	if (!initialized)
	{
		for (uint32_t i = 0; i < 256; ++i)
		{
			uint32_t value = i;
			for (int k = 0; k < 8; ++k)
				value = (value & 1) ? (0xedb88320u ^ (value >> 1)) : (value >> 1);
			table[i] = value;
		}
		initialized = true;
	}

	crc = ~crc;
	for (size_t i = 0; i < size; ++i)
		crc = table[(crc ^ data[i]) & 0xff] ^ (crc >> 8);
	return ~crc;
}

static void writeU32BE(std::string& out, uint32_t value)
{
	out.push_back(char((value >> 24) & 0xff));
	out.push_back(char((value >> 16) & 0xff));
	out.push_back(char((value >> 8) & 0xff));
	out.push_back(char(value & 0xff));
}

static void writePngChunk(std::string& out, const char type[4], const std::string& payload)
{
	writeU32BE(out, uint32_t(payload.size()));

	size_t type_offset = out.size();
	out.append(type, 4);
	out.append(payload);

	uint32_t crc = crc32Update(0, reinterpret_cast<const unsigned char*>(out.data() + type_offset), 4 + payload.size());
	writeU32BE(out, crc);
}

static std::string writePngRGBA(const avifRGBImage& rgb)
{
	static const unsigned char signature[8] = {0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a};

	std::string png;
	png.append(reinterpret_cast<const char*>(signature), 8);

	std::string ihdr;
	writeU32BE(ihdr, rgb.width);
	writeU32BE(ihdr, rgb.height);
	ihdr.push_back(char(8)); // bit depth
	ihdr.push_back(char(6)); // color type RGBA
	ihdr.push_back(char(0)); // compression
	ihdr.push_back(char(0)); // filter
	ihdr.push_back(char(0)); // interlace
	writePngChunk(png, "IHDR", ihdr);

	// build the raw scanline stream (filter byte 0 = none per row) and compute its adler32
	size_t row_size = size_t(rgb.width) * 4;

	std::string idat;
	uint32_t s1 = 1, s2 = 0;

	auto adler_byte = [&](unsigned char byte)
	{
		s1 = (s1 + byte) % 65521;
		s2 = (s2 + s1) % 65521;
	};

	// zlib stream: header (CM=8, CINFO=7), stored DEFLATE blocks (max 65535 payload bytes), adler32
	idat.push_back(char(0x78));
	idat.push_back(char(0x01));

	auto emit_block = [&](const char* payload, size_t size, bool final_block)
	{
		assert(size <= 65535);

		idat.push_back(char(final_block ? 1 : 0)); // BFINAL + BTYPE=0 (stored)
		idat.push_back(char(size & 0xff));         // LEN
		idat.push_back(char((size >> 8) & 0xff));
		idat.push_back(char(~size & 0xff)); // NLEN
		idat.push_back(char((~size >> 8) & 0xff));
		idat.append(payload, size);
	};

	// stream rows through a fixed 65535-byte block buffer so peak memory never holds the full
	// raw image on top of the RGBA working set
	char block[65535];
	size_t block_used = 0;

	auto flush_block = [&](bool final_block)
	{
		if (block_used || final_block)
			emit_block(block, block_used, final_block);
		block_used = 0;
	};

	auto emit_bytes = [&](const char* payload, size_t size)
	{
		while (size)
		{
			size_t take = size;
			if (take > 65535 - block_used)
				take = 65535 - block_used;

			memcpy(block + block_used, payload, take);
			block_used += take;
			payload += take;
			size -= take;

			for (size_t k = 0; k < take; ++k)
				adler_byte((unsigned char)payload[k - take]);

			if (block_used == 65535)
				flush_block(false);
		}
	};

	for (uint32_t y = 0; y < rgb.height; ++y)
	{
		char filter = 0;
		emit_bytes(&filter, 1);
		emit_bytes(reinterpret_cast<const char*>(rgb.pixels + size_t(y) * rgb.rowBytes), row_size);
	}

	flush_block(true);
	writeU32BE(idat, (s2 << 16) | s1);

	writePngChunk(png, "IDAT", idat);
	writePngChunk(png, "IEND", std::string());

	return png;
}

static const char* decodeAvifImage(const std::string& img_data, std::string& png_data)
{
	avifDecoder* decoder = avifDecoderCreate();
	if (!decoder)
		return "error creating AVIF decoder";

	avifResult result = avifDecoderSetIOMemory(decoder, reinterpret_cast<const uint8_t*>(img_data.data()), img_data.size());
	if (result == AVIF_RESULT_OK)
		result = avifDecoderParse(decoder);
	if (result == AVIF_RESULT_OK)
		result = avifDecoderNextImage(decoder);

	if (result != AVIF_RESULT_OK)
	{
		const char* reason = avifResultToString(result);
		avifDecoderDestroy(decoder);
		return reason;
	}

	avifRGBImage rgb;
	avifRGBImageSetDefaults(&rgb, decoder->image);
	rgb.format = AVIF_RGB_FORMAT_RGBA;
	rgb.depth = 8;

	result = avifRGBImageAllocatePixels(&rgb);
	if (result != AVIF_RESULT_OK)
	{
		const char* reason = avifResultToString(result);
		avifDecoderDestroy(decoder);
		return reason;
	}

	result = avifImageYUVToRGB(decoder->image, &rgb);
	if (result != AVIF_RESULT_OK)
	{
		const char* reason = avifResultToString(result);
		avifRGBImageFreePixels(&rgb);
		avifDecoderDestroy(decoder);
		return reason;
	}

	// the decoder keeps the full AVIF bitstream alive; copy the PNG out and release the RGBA
	// working set before the (potentially large) Basis/WebP encode starts, bounding peak memory
	png_data = writePngRGBA(rgb);

	avifRGBImageFreePixels(&rgb);
	avifDecoderDestroy(decoder);

	return NULL;
}

void prepareImagesAvif(const cgltf_data* data, const std::vector<ImageInfo>& images, std::string* encoded, const char* input_path, const Settings& settings, std::string* temp_png)
{
	std::string temp_prefix = getTempPrefix();

	for (size_t i = 0; i < data->images_count; ++i)
	{
		const cgltf_image& image = data->images[i];
		const ImageInfo& info = images[i];

		// only images that are actually scheduled for transcoding need decoding
		if (settings.texture_mode[info.kind] == TextureMode_Raw)
			continue;

		std::string img_data;
		std::string mime_type;
		if (!readImage(image, input_path, img_data, mime_type))
		{
			encoded[i] = "error reading source file";
			continue;
		}

		if (mime_type != "image/avif")
			continue;

		int width = 0, height = 0;
		if (!validateAvif(img_data, &width, &height))
		{
			encoded[i] = "error validating AVIF image";
			continue;
		}

		std::string png_data;
		if (const char* reason = decodeAvifImage(img_data, png_data))
		{
			encoded[i] = std::string("error decoding AVIF image (") + reason + ")";
			continue;
		}

		// release the compressed bitstream before handing the PNG to the encoder
		std::string().swap(img_data);

		temp_png[i] = temp_prefix + "-" + std::to_string(i) + ".png";
		if (!writeFile(temp_png[i].c_str(), png_data))
		{
			encoded[i] = "error writing temporary file";
			temp_png[i].clear();
			continue;
		}

		std::string().swap(png_data);
	}
}

#endif
