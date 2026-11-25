import assert from "node:assert/strict";

const origin = new URL(process.argv[2] ?? "http://127.0.0.1:8080");
assert.match(origin.origin, /^http:\/\/127\.0\.0\.1:\d+$/);
assert.equal(origin.href, origin.origin + "/");
const provider = process.argv[3] ?? "kmas";
assert.ok(["kmas", "naver_webtoon"].includes(provider), "Unsupported provider");

async function get(path) {
    const response = await fetch(new URL(path, origin), {
        redirect: "error",
        signal: AbortSignal.timeout(5000),
    });
    assert.equal(response.status, 200, path);
    return response.json();
}

await get("/api/health");
const ids = new Set();
const externalIds = new Set();
const pageSize = 50;
for (let page = 1; page <= 100; page++) {
    const rows = await get(`/api/webtoons?page=${page}&size=${pageSize}`);
    assert.ok(Array.isArray(rows));
    for (const row of rows) {
        assert.ok(!ids.has(row.id), "Repeated work across pages");
        ids.add(row.id);
        if (row.sourceProvider !== provider || row.externalId?.startsWith("title-search:")) continue;
        assert.ok(Number.isSafeInteger(row.id) && row.id > 0);
        assert.match(row.externalId, /^[A-Za-z0-9][A-Za-z0-9_.-]{0,190}$/);
        const key = row.externalId.toLowerCase();
        assert.ok(!externalIds.has(key), "Duplicate provider work ID");
        const detail = await get(`/api/webtoons/${row.id}`);
        for (const field of ["id", "title", "type", "externalId", "sourceProvider", "servicePlatform"]) {
            assert.equal(detail[field], row[field], field);
        }
        assert.equal(detail.type, "webtoon");
        if (provider === "naver_webtoon") {
            assert.match(detail.externalId, /^[1-9][0-9]*$/);
            assert.ok([
                `https://comic.naver.com/webtoon/list?titleId=${detail.externalId}`,
                `https://m.comic.naver.com/webtoon/list?titleId=${detail.externalId}`,
            ].includes(detail.officialUrl));
        }
        assert.ok(detail.title?.trim() && detail.servicePlatform?.trim());
        const authors = typeof detail.authors === "string" ? JSON.parse(detail.authors) : detail.authors;
        assert.ok(Array.isArray(authors) && authors.length && authors.every(author => author?.trim()));
        externalIds.add(key);
    }
    if (rows.length < pageSize) break;
}
console.log(JSON.stringify({provider, catalogWorks: ids.size, verifiedProviderDetails: externalIds.size}));
assert.ok(externalIds.size >= 5, "Fewer than five official works are available through Spring");
