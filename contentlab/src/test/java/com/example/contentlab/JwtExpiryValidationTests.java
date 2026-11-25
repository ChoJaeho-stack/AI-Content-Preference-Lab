package com.example.contentlab;

import static org.junit.jupiter.api.Assertions.assertThrows;

import java.time.Instant;
import javax.crypto.spec.SecretKeySpec;

import org.junit.jupiter.api.Test;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtValidationException;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import com.nimbusds.jose.jwk.source.ImmutableSecret;

class JwtExpiryValidationTests {

    @Test
    void decoderRejectsAValidlySignedExpiredCookieToken() {
        var key = new SecretKeySpec(new byte[32], "HmacSHA256");
        JwtEncoder encoder = new NimbusJwtEncoder(new ImmutableSecret<>(key));
        JwtDecoder decoder = NimbusJwtDecoder.withSecretKey(key)
                .macAlgorithm(MacAlgorithm.HS256).build();
        Instant expired = Instant.now().minusSeconds(60);
        var claims = JwtClaimsSet.builder()
                .subject("expired-test@example.invalid")
                .issuedAt(expired.minusSeconds(60))
                .expiresAt(expired)
                .claim("memberId", 1L)
                .build();
        String token = encoder.encode(JwtEncoderParameters.from(
                JwsHeader.with(MacAlgorithm.HS256).build(), claims)).getTokenValue();

        assertThrows(JwtValidationException.class, () -> decoder.decode(token));
    }
}
